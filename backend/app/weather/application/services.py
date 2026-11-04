from app.weather.application.dto import LocationSearchResult, TodayWeatherResult
from app.weather.application.exceptions import InvalidWeatherQueryError, WeatherProviderDataError
from app.weather.application.ports import WeatherProvider
from app.weather.domain.models import Coordinates, KST, WeatherForecast


class WeatherService:
    def __init__(self, provider: WeatherProvider) -> None:
        """날씨 제공사 주입"""
        self._provider = provider

    def search_locations(self, query: str, limit: int = 5) -> LocationSearchResult:
        """검색 조건 검증 후 지역 조회"""
        query = query.strip()
        if not 2 <= len(query) <= 100 or not 1 <= limit <= 10:
            raise InvalidWeatherQueryError("지역명은 2~100자, 검색 개수는 1~10이어야 합니다.")
        return LocationSearchResult(self._provider.search_locations(query, limit))

    def get_today(self, latitude: float, longitude: float) -> TodayWeatherResult:
        """오늘 예보와 시간별 정보 구성"""
        forecast = self.get_weekly(latitude, longitude)
        today = forecast.fetched_at.astimezone(KST).date()
        day = next((day for day in forecast.daily if day.date == today), None)
        if day is None:
            raise WeatherProviderDataError()
        hours = tuple(hour for hour in forecast.hourly if hour.time.astimezone(KST).date() == today)
        return TodayWeatherResult(forecast, day, hours, day.summarize())

    def get_weekly(self, latitude: float, longitude: float) -> WeatherForecast:
        """좌표 검증 후 7일 예보 조회"""
        try:
            coordinates = Coordinates(latitude, longitude)
        except ValueError as exc:
            raise InvalidWeatherQueryError(str(exc)) from exc
        return self._provider.get_forecast(coordinates)
