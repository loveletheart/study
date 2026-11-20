"""공유 Redis 예보 캐시와 지역별 갱신 조율."""

import logging
from collections.abc import Callable
from datetime import date, datetime
from math import ceil
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from redis import Redis
from redis.exceptions import RedisError

from app.weather.application.dto import ForecastResult
from app.weather.application.exceptions import (
    WeatherError,
    WeatherProviderDataError,
    WeatherProviderTimeoutError,
)
from app.weather.domain.models import Coordinates, WeatherForecast
from app.weather.infrastructure.forecast_cache import ForecastCacheBase, MemoryForecastCache, TRANSIENT_ERRORS


logger = logging.getLogger(__name__)
FORECAST_ADAPTER = TypeAdapter(WeatherForecast)
CACHEABLE_ERRORS = (*TRANSIENT_ERRORS, WeatherProviderDataError)
PROVIDER_ERRORS = {
    error.__name__: error for error in CACHEABLE_ERRORS
}
# 임대가 끝난 이전 요청은 새 갱신 결과를 덮어쓸 수 없다.
SAVE_IF_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
end
"""


class RedisForecastCache(ForecastCacheBase):
    def __init__(
        self, client: Redis, *, freshness_seconds: float, max_age_seconds: float,
        weather_timeout_seconds: float, clock: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(freshness_seconds=freshness_seconds, max_age_seconds=max_age_seconds, clock=clock)
        self._client = client
        self._memory = MemoryForecastCache(
            freshness_seconds=freshness_seconds, max_age_seconds=max_age_seconds, clock=self._clock,
        )
        self._lock_seconds = max(30.0, 3 * weather_timeout_seconds)
        self._wait_seconds = weather_timeout_seconds + 1

    def _resolve(
        self, forecast_date: date, coordinates: Coordinates, load: Callable[[], WeatherForecast],
    ) -> ForecastResult:
        latitude = float(coordinates.latitude or 0)
        longitude = float(coordinates.longitude or 0)
        key = f"study:weather:forecast:v1:{{open-meteo:{forecast_date}:{latitude}:{longitude}}}"
        lock_key = f"{key}:refresh"
        token = uuid4().hex
        lock = None
        acquired = False
        cached = None
        try:
            try:
                cached = self._read(key, coordinates)
                result = self._cached_result(key, cached, coordinates)
                if result is not None:
                    return result
                lock = self._client.lock(
                    lock_key, timeout=self._lock_seconds, blocking_timeout=self._wait_seconds, sleep=0.05,
                )
                acquired = lock.acquire(token=token)
                cached = self._read(key, coordinates)
                result = self._cached_result(key, cached, coordinates)
                if result is not None:
                    return result
                if not acquired:
                    return self._stale_or_raise(cached, WeatherProviderTimeoutError())
            except RedisError as exc:
                logger.warning("Redis 예보 캐시 조회 실패, 메모리 캐시 사용: cause=%s", type(exc).__name__)
                return self._memory.get_or_load(coordinates, load)

            try:
                forecast = load()
            except CACHEABLE_ERRORS as exc:
                if acquired:
                    self._save(lock_key, f"{key}:error", token, type(exc).__name__, 5)
                return self._forecast_after_error(coordinates, cached, exc)
            self._memory.remember(coordinates, forecast)
            if acquired and self._usable(forecast, coordinates) and forecast.daily[0].date == forecast_date:
                expires = ceil(self._max_age - self._age(forecast))
                if expires > 0:
                    self._save(lock_key, key, token, FORECAST_ADAPTER.dump_json(forecast), expires)
            return ForecastResult(forecast)
        finally:
            if acquired and lock is not None:
                try:
                    lock.release()
                except RedisError as exc:
                    logger.warning("Redis 예보 갱신 잠금 해제 실패: cause=%s", type(exc).__name__)

    def _read(self, key: str, coordinates: Coordinates) -> WeatherForecast | None:
        payload = self._client.get(key)
        if not isinstance(payload, (bytes, bytearray, str)):
            return None
        try:
            forecast = FORECAST_ADAPTER.validate_json(payload, strict=True)
        except ValidationError:
            return None
        if not self._usable(forecast, coordinates):
            return None
        self._memory.remember(coordinates, forecast)
        return forecast

    def _cached_result(
        self, key: str, cached: WeatherForecast | None, coordinates: Coordinates,
    ) -> ForecastResult | None:
        result = self._fresh_result(cached, coordinates)
        if result is not None:
            return result
        failure = self._client.get(f"{key}:error")
        if isinstance(failure, bytes):
            failure = failure.decode("ascii", errors="replace")
        if not isinstance(failure, str):
            return None
        error = PROVIDER_ERRORS.get(failure)
        return self._forecast_after_error(coordinates, cached, error()) if error is not None else None

    def _forecast_after_error(
        self, coordinates: Coordinates, cached: WeatherForecast | None, error: WeatherError,
    ) -> ForecastResult:
        if isinstance(error, TRANSIENT_ERRORS) and (cached is None or not self._usable(cached, coordinates)):
            return self._memory.stale_after_error(coordinates, error)
        return self._stale_or_raise(cached, error)

    def _save(self, lock_key: str, key: str, token: str, value: str | bytes, seconds: int) -> None:
        try:
            self._client.eval(SAVE_IF_OWNER, 2, lock_key, key, token, value, seconds)
        except RedisError as exc:
            logger.warning("Redis 예보 캐시 저장 실패: cause=%s", type(exc).__name__)
