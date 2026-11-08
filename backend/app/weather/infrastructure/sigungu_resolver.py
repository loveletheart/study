"""브이월드 시군구 경계의 점 포함 조회와 대표 위치 공유."""


# 표준 라이브러리
from contextlib import closing
from datetime import datetime
import logging
from pathlib import Path

# 프로젝트 모듈
from app.common.database import connect_database
from app.common.errors.exceptions import AppError
from app.weather.application.exceptions import (
    InvalidWeatherQueryError,
    RegionNotConfiguredError,
    WeatherProviderDataError,
    WeatherProviderUnavailableError,
)
from app.weather.domain.models import Coordinates, KST, Location, SigunguRegion
from app.weather.infrastructure.http_client import JsonHttpClient


# 로그
logger = logging.getLogger(__name__)


# 외부 API 주소
VWORLD_DATA_URL = "https://api.vworld.kr/req/data"


# 시군구 경계 조회와 저장
class VWorldSigunguResolver:
    def __init__(self, database_path: Path, api_key: str, domain: str = "", http=None, clock=None) -> None:
        """키는 저장·응답하지 않고 공식 코드와 검증한 대표 위치만 저장"""
        self._database_path = database_path
        self._api_key = api_key
        self._domain = domain
        self._http = http or JsonHttpClient()
        self._clock = clock or (lambda: datetime.now(KST))
        with closing(connect_database(database_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS weather_sigungu_regions "
                "(code TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL)",
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS weather_sigungu_points "
                "(latitude REAL NOT NULL, longitude REAL NOT NULL, code TEXT NOT NULL, resolved_at REAL NOT NULL, "
                "PRIMARY KEY(latitude, longitude), FOREIGN KEY(code) REFERENCES weather_sigungu_regions(code))",
            )

    def _region(self, code: str) -> SigunguRegion:
        """최초로 경계 안에 있다고 검증한 좌표를 시군구 공통 대표점으로 유지"""
        with closing(connect_database(self._database_path)) as connection:
            row = connection.execute("SELECT * FROM weather_sigungu_regions WHERE code=?", (code,)).fetchone()
        if row is None:
            raise InvalidWeatherQueryError("먼저 지역 검색 결과의 시군구를 확인해 주세요.")
        return SigunguRegion(row["code"], row["name"], row["latitude"], row["longitude"])

    def get(self, region_id: int) -> Location:
        """사전 생성 대상은 검색 식별자 대신 확인된 시군구 코드로 조회"""
        region = self._region(str(region_id))
        return Location(int(region.code), region.name, region.latitude, region.longitude, "KR", timezone="Asia/Seoul")

    def resolve(self, location: Location) -> SigunguRegion:
        """검색 이름이나 좌표 반올림 대신 공식 경계의 POINT 교차 결과로 묶는다."""
        Coordinates(location.latitude, location.longitude)
        if location.country_code != "KR":
            raise InvalidWeatherQueryError("국내 위치만 시군구로 판정할 수 있습니다.")
        with closing(connect_database(self._database_path)) as connection:
            cached = connection.execute(
                "SELECT code, resolved_at FROM weather_sigungu_points WHERE latitude=? AND longitude=?",
                (location.latitude, location.longitude),
            ).fetchone()
        if cached is not None and cached["resolved_at"] >= self._clock().timestamp() - 86400:
            return self._region(cached["code"])
        try:
            if not self._api_key:
                raise RegionNotConfiguredError()
            region = self._fetch_region(location)
        except AppError as exc:
            if cached is None:
                raise
            logger.warning(
                "시군구 재판정 실패로 만료된 저장 판정 재사용: code=%s, cause=%s",
                cached["code"], type(exc).__name__,
            )
            return self._region(cached["code"])
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "INSERT INTO weather_sigungu_regions VALUES (?, ?, ?, ?) ON CONFLICT(code) DO UPDATE SET name=excluded.name",
                (region.code, region.name, region.latitude, region.longitude),
            )
            connection.execute(
                "INSERT INTO weather_sigungu_points VALUES (?, ?, ?, ?) "
                "ON CONFLICT(latitude, longitude) DO UPDATE SET code=excluded.code, resolved_at=excluded.resolved_at",
                (location.latitude, location.longitude, region.code, self._clock().timestamp()),
            )
        return self._region(region.code)

    def _fetch_region(self, location: Location) -> SigunguRegion:
        """외부 조회와 응답 검증에 성공한 시군구만 반환한다."""
        parameters = {
            "service": "data", "request": "GetFeature", "version": "2.0", "data": "LT_C_ADSIGG_INFO",
            "geomfilter": f"POINT({location.longitude} {location.latitude})", "crs": "EPSG:4326",
            "format": "json", "geometry": "false", "attribute": "true", "size": 2, "key": self._api_key,
        }
        if self._domain:
            parameters["domain"] = self._domain
        try:
            payload = self._http.get(VWORLD_DATA_URL, parameters)
        except AppError:
            raise WeatherProviderUnavailableError("공식 시군구 경계 조회에 실패했습니다. 인증·연결 설정을 확인해 주세요.") from None
        try:
            response = payload["response"]
            if response["status"] == "NOT_FOUND":
                raise InvalidWeatherQueryError("시군구 경계가 확인되는 국내 위치를 선택해 주세요.")
            if response["status"] != "OK":
                raise WeatherProviderUnavailableError("브이월드 인증·도메인 및 시군구 데이터 이용 설정을 확인해 주세요.")
            features = response["result"]["featureCollection"]["features"]
            if not isinstance(features, list):
                raise ValueError("시군구 경계 조회 결과의 목록 형식이 올바르지 않습니다.")
            if len(features) != 1:
                raise InvalidWeatherQueryError("경계에 걸치거나 판정할 수 없는 위치입니다. 구역 안쪽의 위치를 선택해 주세요.")
            properties = features[0]["properties"]
            region = SigunguRegion(properties["sig_cd"], properties["sig_kor_nm"], location.latitude, location.longitude)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise WeatherProviderDataError() from None
        return region
