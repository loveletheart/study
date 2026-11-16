# 프로젝트 모듈
from app.weather.application.dto import ForecastResult, LocationSearchResult, TodayWeatherResult
from app.weather.application.exceptions import InvalidWeatherQueryError, WeatherProviderDataError
from app.weather.application.ports import ForecastCache, LocationCatalog, WeatherProvider, LocationSearch
from app.weather.domain.models import Coordinates, KST, WeatherForecast


class WeatherService:
    def __init__(
        self, provider: WeatherProvider, locations: LocationCatalog | None = None,
        search: LocationSearch | None = None, *, forecast_cache: ForecastCache | None = None,
    ) -> None:
        """날씨 제공사 주입"""
        self._provider = provider
        self._locations = locations
        self._search = search
        self._forecast_cache = forecast_cache

    def search_locations(self, query: str, limit: int = 5, offset: int = 0) -> LocationSearchResult:
        """검색 조건 검증 후 지역 조회"""
        query = query.strip()
        if not 2 <= len(query) <= 100 or not 1 <= limit <= 50 or not 0 <= offset <= 1000000:
            raise InvalidWeatherQueryError("지역명은 2~100자, 검색 개수는 1~50, 시작 위치는 0~1000000이어야 합니다.")
        if self._search is not None:
            result = self._search.search(query, limit, offset)
        else:
            # 외부 제공사만 주입한 기존 호출의 호환 경로. 운영에서는 국내 색인을 사용한다.
            rows = self._provider.search_locations(query, min(offset + limit, 100))
            result = LocationSearchResult(rows[offset:offset + limit], total=len(rows), offset=offset, limit=limit)
        if self._locations is not None:
            self._locations.save(result.locations)
        return result

    def get_today(self, latitude: float, longitude: float) -> TodayWeatherResult:
        """오늘 예보와 시간별 정보 구성"""
        result = self.get_weekly_result(latitude, longitude)
        forecast = result.forecast
        today = forecast.fetched_at.astimezone(KST).date()
        day = next((day for day in forecast.daily if day.date == today), None)
        if day is None:
            raise WeatherProviderDataError()
        hours = tuple(hour for hour in forecast.hourly if hour.time.astimezone(KST).date() == today)
        return TodayWeatherResult(forecast, day, hours, day.summarize(), result.is_stale)

    def get_weekly(self, latitude: float, longitude: float) -> WeatherForecast:
        """추천 갱신에는 유효한 최신 예보만 전달한다."""
        result = self.get_weekly_result(latitude, longitude)
        if result.refresh_error is not None:
            raise result.refresh_error
        return result.forecast

    def get_weekly_result(self, latitude: float, longitude: float) -> ForecastResult:
        """화면 조회에 예보와 장애 시 재사용 상태를 전달한다."""
        try:
            coordinates = Coordinates(latitude, longitude)
        except ValueError as exc:
            raise InvalidWeatherQueryError(str(exc)) from exc
        if self._forecast_cache is None:
            return ForecastResult(self._provider.get_forecast(coordinates))
        return self._forecast_cache.get_or_load(coordinates, lambda: self._provider.get_forecast(coordinates))
