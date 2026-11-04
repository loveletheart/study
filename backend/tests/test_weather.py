"""외부 통신 없이 날씨 변환·캐시·오류 계약을 검증하는 합성 데이터 테스트."""

import copy
import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException

from app.weather.application.exceptions import (
    InvalidWeatherQueryError, WeatherProviderDataError, WeatherProviderTimeoutError,
    WeatherProviderUnavailableError, WeatherRateLimitError,
)
from app.weather.application.services import WeatherService
from app.weather.domain.models import Coordinates, KST
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.http_client import JsonHttpClient
from app.weather.infrastructure.open_meteo import (
    CURRENT_FIELDS, DAILY_FIELDS, HOURLY_FIELDS, OpenMeteoProvider,
)
from app.weather.presentation.router import get_today, get_weekly, search_locations

NOW = datetime(2026, 11, 4, 1, 10, tzinfo=timezone.utc)


def forecast_payload(now: datetime = NOW) -> dict:
    """API 구조와 같은 합성 예보. 실제 날씨 데이터가 아니다."""
    first = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_values = {
        "temperature_2m_min": 8, "temperature_2m_max": 18,
        "apparent_temperature_min": 6, "apparent_temperature_max": 17,
        "precipitation_probability_max": 70, "precipitation_sum": 3,
        "snowfall_sum": 0, "wind_speed_10m_max": 4, "uv_index_max": 3,
        "weather_code": 61,
    }
    hourly_values = {
        "temperature_2m": 12, "apparent_temperature": 10,
        "precipitation_probability": 30, "wind_speed_10m": 2, "weather_code": 2,
    }
    return {
        "timezone": "Asia/Seoul", "utc_offset_seconds": 32400,
        "current_units": dict(CURRENT_FIELDS), "daily_units": dict(DAILY_FIELDS), "hourly_units": dict(HOURLY_FIELDS),
        "current": {
            "time": now.astimezone(KST).replace(tzinfo=None).isoformat(timespec="minutes"),
            "temperature_2m": 12, "apparent_temperature": 10, "relative_humidity_2m": 60,
            "precipitation": 0, "wind_speed_10m": 2, "weather_code": 2, "is_day": 1,
        },
        "daily": {
            "time": [(first + timedelta(days=i)).date().isoformat() for i in range(7)],
            **{key: [value] * 7 for key, value in daily_values.items()},
        },
        "hourly": {
            "time": [(first + timedelta(hours=i)).replace(tzinfo=None).isoformat(timespec="minutes") for i in range(168)],
            **{key: [value] * 168 for key, value in hourly_values.items()},
        },
    }


class WeatherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = forecast_payload()
        self.http = Mock()
        self.http.get.side_effect = lambda *args: copy.deepcopy(self.payload)
        self.now = NOW
        self.provider = OpenMeteoProvider(self.http, TTLCache(600), clock=lambda: self.now)
        self.service = WeatherService(self.provider)

    def test_today_has_korean_summary_24_hours_and_explicit_units(self):
        result = get_today(37.5665, 126.9780, self.service)
        self.assertEqual(result.timezone, "Asia/Seoul")
        self.assertEqual(result.today.date.isoformat(), "2026-11-04")
        self.assertEqual(len(result.hourly), 24)
        self.assertEqual(result.today.temperature_range_c, 10)
        self.assertIn("약한 비", result.summary)
        self.assertIn("70%", result.summary)
        self.assertEqual(result.units.wind_speed, "m/s")
        self.assertTrue(result.current.time.isoformat().endswith("+09:00"))
        self.assertEqual(result.fetched_at, NOW)
        encoded = result.model_dump(mode="json")
        self.assertEqual(encoded["provider"], "Open-Meteo")

    def test_weekly_has_seven_consecutive_days_and_shares_today_cache(self):
        today = self.service.get_today(37.5665, 126.9780)
        weekly = get_weekly(37.5665, 126.9780, self.service)
        self.assertEqual(len(weekly.daily), 7)
        self.assertEqual(weekly.daily[0].date, today.today.date)
        self.assertEqual((weekly.daily[-1].date - weekly.daily[0].date).days, 6)
        self.assertEqual(self.http.get.call_count, 1)
        parameters = self.http.get.call_args.args[1]
        self.assertEqual(parameters["forecast_days"], 7)
        self.assertEqual(parameters["wind_speed_unit"], "ms")

    def test_coordinate_queries_keep_locations_separate(self):
        self.service.get_weekly(37.5, 127)
        self.service.get_weekly(35.1, 129)
        self.assertEqual(self.http.get.call_count, 2)

    def test_invalid_coordinates_reject_nan_infinity_and_out_of_range(self):
        for latitude, longitude in [(91, 127), (37, 181), (float("nan"), 127), (37, float("inf"))]:
            with self.subTest(latitude=latitude, longitude=longitude):
                with self.assertRaises(InvalidWeatherQueryError):
                    self.service.get_weekly(latitude, longitude)
        self.http.get.assert_not_called()

    def test_null_optional_values_remain_unknown_instead_of_zero(self):
        self.payload["daily"]["precipitation_probability_max"] = [None] * 7
        self.payload["current"]["apparent_temperature"] = None
        result = get_today(37, 127, self.service)
        self.assertIsNone(result.current.apparent_temperature_c)
        self.assertIsNone(result.today.precipitation_probability_max_percent)
        self.assertNotIn("강수확률", result.summary)

    def test_unknown_weather_code_is_not_reported_as_clear(self):
        self.payload["daily"]["weather_code"] = [999] * 7
        result = self.service.get_today(37, 127)
        self.assertEqual(result.today.description, "알 수 없는 날씨")

    def test_malformed_or_incomplete_forecasts_are_rejected(self):
        mutations = [
            lambda p: p.update(timezone="UTC"),
            lambda p: p["daily_units"].update(wind_speed_10m_max="km/h"),
            lambda p: p["daily"]["temperature_2m_min"].pop(),
            lambda p: p["daily"]["temperature_2m_min"].__setitem__(0, None),
            lambda p: p["daily"]["temperature_2m_max"].__setitem__(0, float("nan")),
            lambda p: p["daily"]["temperature_2m_min"].__setitem__(0, 30),
            lambda p: p["daily"]["precipitation_probability_max"].__setitem__(0, 101),
            lambda p: p["daily"]["time"].__setitem__(0, "2026-11-03"),
            lambda p: p["hourly"]["time"].__setitem__(1, p["hourly"]["time"][0]),
            lambda p: p["current"].update(is_day=2),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                payload = forecast_payload()
                mutate(payload)
                self.payload = payload
                provider = OpenMeteoProvider(self.http, TTLCache(0), clock=lambda: NOW)
                with self.assertRaises(WeatherProviderDataError):
                    provider.get_forecast(Coordinates(37, 127))

    def test_cache_is_not_reused_across_korean_midnight(self):
        self.now = NOW.replace(hour=14, minute=59)
        self.payload = forecast_payload(self.now)
        first = self.service.get_today(37, 127)
        self.now += timedelta(minutes=2)
        self.payload = forecast_payload(self.now)
        second = self.service.get_today(37, 127)
        self.assertEqual((second.today.date - first.today.date).days, 1)
        self.assertEqual(self.http.get.call_count, 2)

    def test_search_locations_uses_korean_country_filter_and_trims_query(self):
        self.payload = {"results": [{
            "id": 1835848, "name": "서울", "latitude": 37.5665, "longitude": 126.978,
            "country_code": "KR", "country": "대한민국", "timezone": "Asia/Seoul",
        }]}
        result = search_locations(" 서울 ", self.service, 5)
        self.assertEqual(result.locations[0].name, "서울")
        self.assertIsNone(result.locations[0].admin2)
        params = self.http.get.call_args.args[1]
        self.assertEqual(params["name"], "서울")
        self.assertEqual(params["countryCode"], "KR")

    def test_empty_location_search_is_a_successful_empty_list(self):
        self.payload = {"generationtime_ms": 0.1}
        self.assertEqual(self.service.search_locations("없는지역").locations, ())

    def test_blank_or_short_location_search_does_not_call_provider(self):
        for query in (" ", "서", "x" * 101):
            with self.assertRaises(InvalidWeatherQueryError):
                self.service.search_locations(query)
        self.http.get.assert_not_called()

    def test_invalid_geocoding_payload_is_rejected(self):
        self.payload = {"results": None}
        with self.assertRaises(WeatherProviderDataError):
            self.service.search_locations("서울")

    def test_provider_failures_map_to_public_http_status_codes(self):
        for error, expected in [
            (WeatherProviderTimeoutError("timeout"), 504),
            (WeatherProviderUnavailableError("unavailable"), 503),
            (WeatherRateLimitError("rate limit"), 503),
            (WeatherProviderDataError("bad data"), 502),
        ]:
            with self.subTest(error=error):
                self.http.get.side_effect = error
                with self.assertRaises(HTTPException) as caught:
                    get_today(37, 127, self.service)
                self.assertEqual(caught.exception.status_code, expected)

    def test_error_is_not_cached_and_next_request_can_recover(self):
        self.http.get.side_effect = [WeatherProviderTimeoutError("timeout"), forecast_payload()]
        with self.assertRaises(WeatherProviderTimeoutError):
            self.service.get_weekly(37, 127)
        self.assertEqual(len(self.service.get_weekly(37, 127).daily), 7)


class CacheTests(unittest.TestCase):
    def test_ttl_expiry_and_capacity(self):
        now = [0.0]
        cache = TTLCache(10, max_entries=2, timer=lambda: now[0])
        load = Mock(side_effect=range(10))
        self.assertEqual(cache.get_or_load(("a",), load), 0)
        self.assertEqual(cache.get_or_load(("a",), load), 0)
        now[0] = 11
        self.assertEqual(cache.get_or_load(("a",), load), 1)
        cache.get_or_load(("b",), load)
        cache.get_or_load(("c",), load)
        self.assertEqual(cache.get_or_load(("a",), load), 4)


class HttpClientTests(unittest.TestCase):
    @patch("app.weather.infrastructure.http_client.urlopen")
    def test_utf8_parameters_response_and_timeout(self, urlopen):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({"results": []}).encode()
        urlopen.return_value = response
        result = JsonHttpClient(3).get("https://example.com/search", {"name": "서울"})
        self.assertEqual(result, {"results": []})
        request = urlopen.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(request.full_url).query)["name"], ["서울"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 3)

    @patch("app.weather.infrastructure.http_client.urlopen")
    def test_network_and_http_errors_are_classified(self, urlopen):
        for error, expected in [
            (TimeoutError(), WeatherProviderTimeoutError),
            (URLError(TimeoutError()), WeatherProviderTimeoutError),
            (URLError("DNS failure"), WeatherProviderUnavailableError),
            (IncompleteRead(b"partial response"), WeatherProviderUnavailableError),
            (HTTPError("url", 429, "limit", {}, io.BytesIO()), WeatherRateLimitError),
            (HTTPError("url", 500, "server", {}, io.BytesIO()), WeatherProviderUnavailableError),
            (HTTPError("url", 400, "bad", {}, io.BytesIO()), WeatherProviderDataError),
        ]:
            with self.subTest(error=error):
                urlopen.side_effect = error
                with self.assertRaises(expected):
                    JsonHttpClient().get("https://example.com", {})

    @patch("app.weather.infrastructure.http_client.urlopen")
    def test_invalid_json_error_objects_and_oversized_responses(self, urlopen):
        for body in (b"not-json", b"[]", b'{"error": true}', b"x" * 1_048_577):
            with self.subTest(body_length=len(body)):
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.read.return_value = body
                urlopen.return_value = response
                with self.assertRaises(WeatherProviderDataError):
                    JsonHttpClient().get("https://example.com", {})


if __name__ == "__main__":
    unittest.main()
