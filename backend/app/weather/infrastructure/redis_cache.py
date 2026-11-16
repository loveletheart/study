"""공유 Redis 예보 캐시와 지역별 갱신 조율."""

import logging
from collections.abc import Callable
from concurrent.futures import Future
from datetime import date, datetime
from math import ceil
from threading import Lock
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from redis import Redis
from redis.exceptions import RedisError

from app.weather.application.dto import ForecastResult
from app.weather.application.exceptions import (
    WeatherError,
    WeatherProviderDataError,
    WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
    WeatherRateLimitError,
)
from app.weather.domain.models import KST, Coordinates, WeatherForecast


logger = logging.getLogger(__name__)
FORECAST_ADAPTER = TypeAdapter(WeatherForecast)
TRANSIENT_ERRORS = (WeatherProviderTimeoutError, WeatherProviderUnavailableError, WeatherRateLimitError)
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


class RedisForecastCache:
    def __init__(
        self, client: Redis, *, freshness_seconds: float, max_age_seconds: float,
        weather_timeout_seconds: float, clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._freshness = freshness_seconds
        self._max_age = max_age_seconds
        self._lock_seconds = max(30.0, 3 * weather_timeout_seconds)
        self._wait_seconds = weather_timeout_seconds + 1
        self._clock = clock or (lambda: datetime.now(KST))
        self._guard = Lock()
        self._pending: dict[str, Future[ForecastResult]] = {}

    def get_or_load(self, coordinates: Coordinates, load: Callable[[], WeatherForecast]) -> ForecastResult:
        now = self._clock().astimezone(KST)
        latitude = float(coordinates.latitude or 0)
        longitude = float(coordinates.longitude or 0)
        key = f"study:weather:forecast:v1:{{open-meteo:{now.date()}:{latitude}:{longitude}}}"
        with self._guard:
            pending: Future[ForecastResult] | None = self._pending.get(key)
            owns_request = pending is None
            if pending is None:
                pending = Future()
                self._pending[key] = pending
        if not owns_request:
            return pending.result()
        try:
            result = self._resolve(key, now.date(), coordinates, load)
            pending.set_result(result)
            return result
        except BaseException as exc:
            pending.set_exception(exc)
            raise
        finally:
            with self._guard:
                self._pending.pop(key)

    def _resolve(
        self, key: str, forecast_date: date, coordinates: Coordinates, load: Callable[[], WeatherForecast],
    ) -> ForecastResult:
        lock_key = f"{key}:refresh"
        token = uuid4().hex
        lock = None
        acquired = False
        cached = None
        try:
            try:
                cached = self._read(key, coordinates)
                result = self._cached_result(key, cached)
                if result is not None:
                    return result
                lock = self._client.lock(
                    lock_key, timeout=self._lock_seconds, blocking_timeout=self._wait_seconds, sleep=0.05,
                )
                acquired = lock.acquire(token=token)
                cached = self._read(key, coordinates)
                result = self._cached_result(key, cached)
                if result is not None:
                    return result
                if not acquired:
                    return self._stale_or_raise(cached, WeatherProviderTimeoutError())
            except RedisError as exc:
                logger.warning("Redis 예보 캐시 조회 실패: cause=%s", type(exc).__name__)

            try:
                forecast = load()
            except CACHEABLE_ERRORS as exc:
                if acquired:
                    self._save(lock_key, f"{key}:error", token, type(exc).__name__, 5)
                return self._stale_or_raise(cached, exc)
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
        return forecast if self._usable(forecast, coordinates) else None

    def _cached_result(self, key: str, cached: WeatherForecast | None) -> ForecastResult | None:
        if cached is not None:
            now = self._clock().astimezone(KST)
            age = now.timestamp() - cached.fetched_at.timestamp()
            if cached.daily[0].date == now.date() and 0 <= age < self._freshness:
                return ForecastResult(cached)
        failure = self._client.get(f"{key}:error")
        if isinstance(failure, bytes):
            failure = failure.decode("ascii", errors="replace")
        if not isinstance(failure, str):
            return None
        error = PROVIDER_ERRORS.get(failure)
        return self._stale_or_raise(cached, error()) if error is not None else None

    def _stale_or_raise(self, cached: WeatherForecast | None, error: WeatherError) -> ForecastResult:
        if isinstance(error, TRANSIENT_ERRORS) and cached is not None and self._usable(cached, cached.coordinates):
            return ForecastResult(cached, error)
        raise error

    def _age(self, forecast: WeatherForecast) -> float:
        return self._clock().timestamp() - forecast.fetched_at.timestamp()

    def _usable(self, forecast: WeatherForecast, coordinates: Coordinates) -> bool:
        now = self._clock().astimezone(KST)
        return (
            forecast.coordinates == coordinates
            and forecast.timezone == "Asia/Seoul"
            and forecast.provider == "Open-Meteo"
            and forecast.fetched_at.utcoffset() is not None
            and 0 <= now.timestamp() - forecast.fetched_at.timestamp() < self._max_age
            and len(forecast.daily) == 7
            and forecast.daily[0].date == forecast.fetched_at.astimezone(KST).date() == now.date()
            and len(forecast.hourly) == 168
        )

    def _save(self, lock_key: str, key: str, token: str, value: str | bytes, seconds: int) -> None:
        try:
            self._client.eval(SAVE_IF_OWNER, 2, lock_key, key, token, value, seconds)
        except RedisError as exc:
            logger.warning("Redis 예보 캐시 저장 실패: cause=%s", type(exc).__name__)

