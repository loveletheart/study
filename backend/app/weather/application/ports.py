"""외부 날씨·지역 조회에 필요한 인터페이스. 저장소 인터페이스와 구분한다."""

# 표준 라이브러리
from typing import Protocol

# 프로젝트 모듈
from app.weather.domain.models import Coordinates, Location, SigunguRegion, WeatherForecast
from app.weather.application.dto import LocationSearchResult


class LocationSearch(Protocol):
    def search(self, query: str, limit: int, offset: int) -> LocationSearchResult:
        """지역 이름·별칭·상위 지역의 부분 일치 검색과 페이지 정보."""
        ...


class WeatherProvider(Protocol):
    def search_locations(self, query: str, limit: int) -> tuple[Location, ...]:
        """지역 검색 인터페이스"""
        ...

    def get_forecast(self, coordinates: Coordinates) -> WeatherForecast:
        """날씨 예보 조회 인터페이스"""
        ...


class LocationReader(Protocol):
    def get(self, location_id: int, /) -> Location:
        """저장 기능 없이 식별자로 대표 위치를 조회하는 계약."""
        ...


class LocationCatalog(LocationReader, Protocol):
    def save(self, locations: tuple[Location, ...]) -> None:
        """제공사에서 검증한 지역 검색 결과 보관"""
        ...


class SigunguResolver(LocationReader, Protocol):
    def resolve(self, location: Location) -> SigunguRegion:
        """대표 위치의 좌표를 공식 시군구 경계로 판정"""
        ...
