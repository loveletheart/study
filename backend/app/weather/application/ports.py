"""외부 날씨·지역 조회에 필요한 인터페이스. 저장소 인터페이스와 구분한다."""

from typing import Protocol

from app.weather.domain.models import Coordinates, Location, WeatherForecast


class WeatherProvider(Protocol):
    def search_locations(self, query: str, limit: int) -> tuple[Location, ...]: ...

    def get_forecast(self, coordinates: Coordinates) -> WeatherForecast: ...
