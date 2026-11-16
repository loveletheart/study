"""메모리·Redis 예보 캐시의 공통 유효기간과 동시 갱신 처리."""

from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from datetime import date, datetime
from threading import Lock

from app.weather.application.dto import ForecastResult
from app.weather.application.exceptions import (
    WeatherError,
    WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
    WeatherRateLimitError,
)
from app.weather.domain.models import KST, Coordinates, WeatherForecast


TRANSIENT_ERRORS = (WeatherProviderTimeoutError, WeatherProviderUnavailableError, WeatherRateLimitError)


class ForecastCacheBase(ABC):
    def __init__(
        self, *, freshness_seconds: float, max_age_seconds: float, clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._freshness = freshness_seconds
        self._max_age = max_age_seconds
        self._clock = clock or (lambda: datetime.now(KST))
        self._guard = Lock()
        self._pending: dict[tuple[date, Coordinates], Future[ForecastResult]] = {}

    def get_or_load(self, coordinates: Coordinates, load: Callable[[], WeatherForecast]) -> ForecastResult:
        forecast_date = self._clock().astimezone(KST).date()
        key = (forecast_date, coordinates)
        with self._guard:
            pending = self._pending.get(key)
            owns_request = pending is None
            if pending is None:
                pending = Future()
                self._pending[key] = pending
        if not owns_request:
            return pending.result()
        try:
            result = self._resolve(forecast_date, coordinates, load)
            pending.set_result(result)
            return result
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._guard:
                self._pending.pop(key)

    @abstractmethod
    def _resolve(
        self, forecast_date: date, coordinates: Coordinates, load: Callable[[], WeatherForecast],
    ) -> ForecastResult: ...

    def _fresh_result(self, cached: WeatherForecast | None, coordinates: Coordinates) -> ForecastResult | None:
        if cached is not None and self._usable(cached, coordinates, self._freshness):
            return ForecastResult(cached)
        return None

    def _stale_or_raise(self, cached: WeatherForecast | None, error: WeatherError) -> ForecastResult:
        if isinstance(error, TRANSIENT_ERRORS) and cached is not None and self._usable(cached, cached.coordinates):
            return ForecastResult(cached, error)
        raise error

    def _age(self, forecast: WeatherForecast) -> float:
        return self._clock().timestamp() - forecast.fetched_at.timestamp()

    def _usable(
        self, forecast: WeatherForecast, coordinates: Coordinates, freshness: float | None = None,
    ) -> bool:
        now = self._clock().astimezone(KST)
        age_limit = self._max_age if freshness is None else min(self._max_age, freshness)
        return (
            forecast.coordinates == coordinates
            and forecast.timezone == "Asia/Seoul"
            and forecast.provider == "Open-Meteo"
            and forecast.fetched_at.utcoffset() is not None
            and 0 <= now.timestamp() - forecast.fetched_at.timestamp() < age_limit
            and len(forecast.daily) == 7
            and forecast.daily[0].date == forecast.fetched_at.astimezone(KST).date() == now.date()
            and len(forecast.hourly) == 168
        )


class MemoryForecastCache(ForecastCacheBase):
    def __init__(
        self, *, freshness_seconds: float, max_age_seconds: float, clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(freshness_seconds=freshness_seconds, max_age_seconds=max_age_seconds, clock=clock)
        self._entries: OrderedDict[tuple[date, Coordinates], WeatherForecast] = OrderedDict()

    def _resolve(
        self, forecast_date: date, coordinates: Coordinates, load: Callable[[], WeatherForecast],
    ) -> ForecastResult:
        key = (forecast_date, coordinates)
        with self._guard:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)

        result = self._fresh_result(cached, coordinates)
        if result is not None:
            return result
        try:
            forecast = load()
        except TRANSIENT_ERRORS as exc:
            return self._stale_or_raise(cached, exc)

        if self._usable(forecast, coordinates) and forecast.daily[0].date == forecast_date:
            with self._guard:
                self._entries[key] = forecast
                self._entries.move_to_end(key)
                if len(self._entries) > 128:
                    self._entries.popitem(last=False)
        return ForecastResult(forecast)
