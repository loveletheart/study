"""외부 날씨·지역 조회에 필요한 인터페이스. 저장소 인터페이스와 구분한다."""

# 표준 라이브러리
from typing import Protocol

# 프로젝트 모듈
from app.weather.domain.models import Coordinates, Location, SigunguRegion, WeatherForecast


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


class LocationCatalog(Protocol):
    def save(self, locations: tuple[Location, ...]) -> None:
        """제공사에서 검증한 지역 검색 결과 보관"""
        ...

    def get(self, location_id: int) -> Location:
        """검색에서 선택한 지역 식별자로 대표 위치 조회"""
        ...


class SigunguResolver(Protocol):
    def resolve(self, location: Location) -> SigunguRegion:
        """대표 위치의 좌표를 공식 시군구 경계로 판정"""
        ...

    def get(self, region_id: int) -> Location:
        """검증한 시군구 코드의 고정 대표 위치 조회"""
        ...
