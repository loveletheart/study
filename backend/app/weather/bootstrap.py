# 표준 라이브러리
from functools import lru_cache

# 프로젝트 모듈
from app.common.config import get_settings
from app.weather.application.services import WeatherService
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.http_client import JsonHttpClient
from app.weather.infrastructure.open_meteo import OpenMeteoProvider
from app.weather.infrastructure.location_catalog import SQLiteLocationCatalog, SQLiteLocationSearch
from app.weather.infrastructure.sigungu_resolver import VWorldSigunguResolver


@lru_cache
def get_weather_provider() -> OpenMeteoProvider:
    """날씨 API 클라이언트와 캐시 구성"""
    settings = get_settings()
    return OpenMeteoProvider(
        http=JsonHttpClient(settings.weather_timeout_seconds),
        cache=TTLCache(settings.weather_cache_ttl_seconds),
    )


def get_weather_service() -> WeatherService:
    """날씨 제공사와 서비스 연결"""
    return WeatherService(get_weather_provider(), get_location_catalog(), get_location_search())


@lru_cache
def get_location_search() -> SQLiteLocationSearch:
    """검색 시 외부 호출 없이 국내 자료의 포함 검색과 페이지 조회를 사용한다."""
    return SQLiteLocationSearch(get_settings().database_path)


@lru_cache
def get_location_catalog() -> SQLiteLocationCatalog:
    """같은 지역 검색 목록을 서버 재시작 후에도 공유"""
    return SQLiteLocationCatalog(get_settings().database_path)


@lru_cache
def get_sigungu_resolver() -> VWorldSigunguResolver:
    """공식 시군구 경계 판정과 대표 좌표 저장소 구성"""
    settings = get_settings()
    return VWorldSigunguResolver(settings.database_path, settings.vworld_api_key, settings.vworld_domain)
