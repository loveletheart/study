"""외부 날씨·지역 조회에 필요한 인터페이스. 저장소 인터페이스와 구분한다."""

from typing import Protocol

from app.weather.domain.models import Coordinates, Location, WeatherForecast


class WeatherProvider(Protocol):
    # 지역 검색 인터페이스
    def search_locations(self, query: str, limit: int) -> tuple[Location, ...]:
        ...

    # 날씨 예보 조회 인터페이스
    def get_forecast(self, coordinates: Coordinates) -> WeatherForecast:
        ...
