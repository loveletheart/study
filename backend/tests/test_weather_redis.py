"""공유 캐시로 날씨 API와 추천 갱신의 예보 정책을 검증한다."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock, patch

from redis.exceptions import ConnectionError as RedisConnectionError, RedisError

from app.common.config import Settings
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.weather.application.exceptions import (
    WeatherProviderDataError,
    WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
    WeatherRateLimitError,
)
from app.weather.application.services import WeatherService
from app.weather.bootstrap import get_forecast_cache
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.open_meteo import OpenMeteoProvider
from app.weather.infrastructure.redis_cache import RedisForecastCache
from app.weather.presentation.router import get_today, get_weekly
from tests.test_weather import NOW, forecast_payload


class FakeRedisLock:
    def __init__(self, client, name, mutex, blocking_timeout):
        self.client = client
        self.name = name
        self.mutex = mutex
        self.blocking_timeout = blocking_timeout

    def acquire(self, *, token):
        self.client.lock_started.set()
        if not self.mutex.acquire(timeout=self.blocking_timeout):
            return False
        with self.client.guard:
            self.client.values[self.name] = (token, float("inf"))
        return True

    def release(self):
        with self.client.guard:
            self.client.values.pop(self.name)
        self.mutex.release()


class FakeRedis:
    def __init__(self, clock):
        self.clock = clock
        self.guard = Lock()
        self.lock_started = Event()
        self.values = {}
        self.locks = {}

    def get(self, key):
        with self.guard:
            value = self.values.get(key)
            if value is not None and self.clock().timestamp() < value[1]:
                return value[0]

    def lock(self, name, *, timeout, blocking_timeout, sleep):
        with self.guard:
            mutex = self.locks.setdefault(name, Lock())
        return FakeRedisLock(self, name, mutex, blocking_timeout)

    def eval(self, script, numkeys, lock_key, key, token, value, seconds):
        with self.guard:
            owner = self.values.get(lock_key)
            if owner is not None and owner[0] == token:
                self.values[key] = (value, self.clock().timestamp() + seconds)
                return True


class RedisWeatherTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.redis = FakeRedis(lambda: self.now)
        self.http = Mock()
        self.http.get.side_effect = lambda *args: forecast_payload(self.now)
        self.service = self.make_service()

    def make_service(self):
        provider = OpenMeteoProvider(self.http, TTLCache(0), clock=lambda: self.now)
        cache = RedisForecastCache(
            self.redis, freshness_seconds=3600, max_age_seconds=10800,
            weather_timeout_seconds=2, clock=lambda: self.now,
        )
        return WeatherService(provider, forecast_cache=cache)

    def test_restarted_service_shares_fresh_forecast_with_weekly_and_outfits(self):
        first = get_today(37, 127, self.service).data
        self.now += timedelta(minutes=50)
        restarted = self.make_service()
        weekly = get_weekly(37, 127, restarted).data
        outfit = WeatherServiceReader(restarted).get_forecast(37, 127)

        self.assertFalse(first.is_stale)
        self.assertFalse(weekly.is_stale)
        self.assertEqual(first.fetched_at, weekly.fetched_at)
        self.assertEqual(outfit.fetched_at, first.fetched_at)
        self.http.get.assert_called_once()

    def test_only_one_provider_call_across_service_instances(self):
        started, release = Event(), Event()
        restarted = self.make_service()

        def load(*args):
            started.set()
            if not release.wait(5):
                raise AssertionError("Forecast request was not released")
            return forecast_payload(self.now)

        self.http.get.side_effect = load
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.get_weekly, 37, 127)
            try:
                self.assertTrue(started.wait(2))
                self.redis.lock_started.clear()
                second = pool.submit(restarted.get_weekly, 37, 127)
                self.assertTrue(self.redis.lock_started.wait(2))
                self.assertFalse(second.done())
            finally:
                release.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
        self.http.get.assert_called_once()

    def test_weather_can_show_stale_data_but_outfits_passes_through_the_failure(self):
        for error in (WeatherProviderTimeoutError, WeatherProviderUnavailableError, WeatherRateLimitError):
            with self.subTest(error=error.__name__):
                self.setUp()
                first = get_today(37, 127, self.service).data
                self.now += timedelta(hours=1, minutes=5)
                self.http.get.side_effect = error()

                stale = get_today(37, 127, self.service).data
                weekly = get_weekly(37, 127, self.make_service()).data
                self.assertTrue(stale.is_stale)
                self.assertTrue(weekly.is_stale)
                self.assertEqual(stale.fetched_at, first.fetched_at)
                self.assertEqual(weekly.fetched_at, first.fetched_at)
                self.assertEqual(stale.today, first.today)
                with self.assertRaises(error):
                    WeatherServiceReader(self.service).get_forecast(37, 127)
                self.assertEqual(self.http.get.call_count, 2)

                self.now += timedelta(seconds=6)
                self.http.get.side_effect = lambda *args: forecast_payload(self.now)
                refreshed = get_today(37, 127, self.service).data
                self.assertFalse(refreshed.is_stale)
                self.assertEqual(refreshed.fetched_at, self.now)

    def test_fallback_requires_same_korean_date_and_unexpired_retention(self):
        for before, delta in (
            (NOW, timedelta(hours=3)),
            (NOW.replace(hour=14, minute=58), timedelta(minutes=3)),
        ):
            with self.subTest(before=before, delta=delta):
                self.setUp()
                self.now = before
                self.service.get_today(37, 127)
                self.now += delta
                self.http.get.side_effect = WeatherProviderTimeoutError()
                with self.assertRaises(WeatherProviderTimeoutError):
                    self.make_service().get_today(37, 127)

    def test_provider_validation_error_does_not_return_or_replace_previous_forecast(self):
        self.service.get_today(37, 127)
        before = next(value for key, value in self.redis.values.items() if not key.endswith(":refresh"))
        self.now += timedelta(minutes=61)
        self.http.get.side_effect = lambda *args: {"timezone": "unsupported"}
        with self.assertRaises(WeatherProviderDataError):
            self.service.get_today(37, 127)
        self.assertIn(before, self.redis.values.values())

    def test_redis_outage_does_not_prevent_a_live_weather_lookup(self):
        self.redis.get = Mock(side_effect=RedisError())
        with self.assertLogs("app.weather.infrastructure.redis_cache", level="WARNING"):
            result = get_today(37, 127, self.service).data
        self.assertFalse(result.is_stale)
        self.http.get.assert_called_once()

    def test_cached_forecast_is_rechecked_when_midnight_passes_during_read(self):
        self.now = NOW.replace(hour=14, minute=59)
        old = self.service.get_weekly(37, 127)
        cache = self.service._forecast_cache
        assert isinstance(cache, RedisForecastCache)
        read = cache._read

        def read_at_day_boundary(*args):
            forecast = read(*args)
            self.now = old.fetched_at + timedelta(minutes=1)
            return forecast

        with patch.object(cache, "_read", side_effect=read_at_day_boundary):
            current = self.service.get_weekly(37, 127)

        self.assertEqual(current.daily[0].date, old.daily[0].date + timedelta(days=1))
        self.assertEqual(self.http.get.call_count, 2)

    def test_bootstrap_shares_client_with_short_timeouts_and_no_retries(self):
        settings = Settings("Test", Path("unused.db"), weather_redis_url="redis://localhost:6379/0")
        get_forecast_cache.cache_clear()
        self.addCleanup(get_forecast_cache.cache_clear)
        with (
            patch("app.weather.bootstrap.get_settings", return_value=settings),
            patch("redis.Redis.from_url", return_value=self.redis) as from_url,
        ):
            cache = get_forecast_cache()
            self.assertIsInstance(cache, RedisForecastCache)
            self.assertIs(get_forecast_cache(), cache)
        from_url.assert_called_once()
        self.assertEqual(from_url.call_args.args, (settings.weather_redis_url,))
        self.assertEqual(from_url.call_args.kwargs["socket_connect_timeout"], 1)
        self.assertEqual(from_url.call_args.kwargs["socket_timeout"], 1)

        connect = Mock(side_effect=RedisConnectionError())
        with self.assertRaises(RedisConnectionError):
            from_url.call_args.kwargs["retry"].call_with_retry(connect, lambda error: None)
        connect.assert_called_once()

