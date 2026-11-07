"""공식 경계 판정의 코드 공유·실패 처리와 키 비노출을 검증한다."""

import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

from app.common.database import connect_database
from app.weather.application.exceptions import (
    InvalidWeatherQueryError, RegionNotConfiguredError, WeatherProviderDataError, WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
)
from app.weather.domain.models import Location
from app.weather.infrastructure.sigungu_resolver import VWorldSigunguResolver
from tests.test_weather import NOW


def boundary_response(code="99001", name="검증용 시군구"):
    """실제 지역이 아닌 검증용 공식 응답 구조"""
    return {"response": {"status": "OK", "result": {"featureCollection": {
        "features": [{"properties": {"sig_cd": code, "sig_kor_nm": name}}],
    }}}}


class SigunguTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "regions.db"
        self.http = Mock()
        self.http.get.return_value = boundary_response()
        self.now = NOW
        self.resolver = VWorldSigunguResolver(
            self.database_path, "test-private-key", "http://localhost:8000", self.http, lambda: self.now,
        )
        self.location = Location(1001, "검증 검색 위치", 37, 127, "KR")

    def test_point_filter_uses_longitude_latitude_and_official_sigungu_layer(self):
        region = self.resolver.resolve(self.location)
        parameters = self.http.get.call_args.args[1]
        self.assertEqual(parameters["data"], "LT_C_ADSIGG_INFO")
        self.assertEqual(parameters["geomfilter"], "POINT(127 37)")
        self.assertEqual(parameters["crs"], "EPSG:4326")
        self.assertEqual(parameters["domain"], "http://localhost:8000")
        self.assertEqual(region.code, "99001")
        self.assertNotIn("test-private-key", repr(region))

    def test_same_official_code_preserves_fixed_representative_point(self):
        first = self.resolver.resolve(self.location)
        second = self.resolver.resolve(replace(self.location, id=1002, latitude=37.01))
        self.assertEqual(first, second)
        stored = self.resolver.get(99001)
        self.assertEqual((stored.latitude, stored.longitude), (37, 127))
        self.assertEqual(stored.id, 99001)

    def test_different_official_codes_do_not_share_representative_points(self):
        first = self.resolver.resolve(self.location)
        self.http.get.return_value = boundary_response("99002", "다른 검증 시군구")
        second = self.resolver.resolve(replace(self.location, latitude=38))
        self.assertNotEqual(first.code, second.code)
        self.assertEqual((second.latitude, second.longitude), (38, 127))

    def test_coordinate_mapping_reuses_storage_and_rechecks_after_one_day(self):
        first = self.resolver.resolve(self.location)
        restarted = VWorldSigunguResolver(self.database_path, "test-private-key", http=self.http, clock=lambda: self.now)
        self.assertEqual(restarted.resolve(self.location), first)
        self.http.get.assert_called_once()
        self.now += timedelta(days=1, seconds=1)
        restarted.resolve(self.location)
        self.assertEqual(self.http.get.call_count, 2)

    def test_missing_key_and_unknown_region_fail_explicitly(self):
        resolver = VWorldSigunguResolver(self.database_path, "", http=self.http)
        with self.assertRaises(RegionNotConfiguredError):
            resolver.resolve(self.location)
        with self.assertRaises(InvalidWeatherQueryError):
            resolver.get(99001)
        self.http.get.assert_not_called()

    def test_expired_mapping_survives_restart_without_key(self):
        first = self.resolver.resolve(self.location)
        self.now += timedelta(days=2)
        self.http.reset_mock()
        restarted = VWorldSigunguResolver(self.database_path, "", http=self.http, clock=lambda: self.now)
        with self.assertLogs("app.weather.infrastructure.sigungu_resolver", level="WARNING") as logs:
            self.assertEqual(restarted.resolve(self.location), first)
        self.http.get.assert_not_called()
        self.assertIn("RegionNotConfiguredError", " ".join(logs.output))
        self.assertIn(first.code, " ".join(logs.output))
        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute("SELECT resolved_at FROM weather_sigungu_points").fetchone()
        self.assertEqual(row["resolved_at"], NOW.timestamp())

    def test_expired_mapping_survives_http_errors_without_renewing_timestamp(self):
        first = self.resolver.resolve(self.location)
        self.now += timedelta(days=2)
        for error in (WeatherProviderTimeoutError, WeatherProviderUnavailableError, WeatherProviderDataError):
            with self.subTest(error=error):
                self.http.get.side_effect = error("private URL with test-private-key")
                before = self.http.get.call_count
                with self.assertLogs("app.weather.infrastructure.sigungu_resolver", level="WARNING") as logs:
                    self.assertEqual(self.resolver.resolve(self.location), first)
                    self.assertEqual(self.resolver.resolve(self.location), first)
                self.assertEqual(self.http.get.call_count, before + 2)
                self.assertNotIn("test-private-key", " ".join(logs.output))
                self.assertNotIn("private URL", " ".join(logs.output))
        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute("SELECT resolved_at FROM weather_sigungu_points").fetchone()
        self.assertEqual(row["resolved_at"], NOW.timestamp())

    def test_expired_mapping_survives_provider_status_and_validation_errors(self):
        first = self.resolver.resolve(self.location)
        self.now += timedelta(days=2)
        for payload in (
            {"response": {"status": "ERROR", "error": {"text": "test-private-key"}}},
            {"response": {"status": "NOT_FOUND"}},
            {"response": {"status": "OK", "result": {"featureCollection": {"features": [{}, {}]}}}},
            boundary_response("invalid-code"),
            {},
        ):
            with self.subTest(payload=payload):
                self.http.get.return_value = payload
                with self.assertLogs("app.weather.infrastructure.sigungu_resolver", level="WARNING") as logs:
                    self.assertEqual(self.resolver.resolve(self.location), first)
                self.assertNotIn("test-private-key", " ".join(logs.output))

    def test_successful_recheck_replaces_expired_point_mapping(self):
        self.resolver.resolve(self.location)
        self.now += timedelta(days=2)
        self.http.get.return_value = boundary_response("99002", "변경된 검증 시군구")
        updated = self.resolver.resolve(self.location)
        self.assertEqual(updated.code, "99002")
        self.assertEqual(self.resolver.resolve(self.location), updated)
        self.assertEqual(self.http.get.call_count, 2)
        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute("SELECT code, resolved_at FROM weather_sigungu_points").fetchone()
        self.assertEqual(row["code"], "99002")
        self.assertEqual(row["resolved_at"], self.now.timestamp())

    def test_stale_region_for_another_point_is_not_used(self):
        self.resolver.resolve(self.location)
        self.now += timedelta(days=2)
        other = replace(self.location, latitude=38)
        no_key = VWorldSigunguResolver(self.database_path, "", http=self.http, clock=lambda: self.now)
        with self.assertRaises(RegionNotConfiguredError):
            no_key.resolve(other)
        self.http.get.side_effect = WeatherProviderTimeoutError()
        with self.assertRaises(WeatherProviderUnavailableError):
            self.resolver.resolve(other)

    def test_stale_mapping_does_not_mask_invalid_input_or_unexpected_errors(self):
        self.resolver.resolve(self.location)
        self.now += timedelta(days=2)
        with self.assertRaises(InvalidWeatherQueryError):
            self.resolver.resolve(replace(self.location, country_code="US"))
        self.http.get.side_effect = RuntimeError("unexpected implementation failure")
        with self.assertRaises(RuntimeError):
            self.resolver.resolve(self.location)

    def test_outside_boundary_and_multiple_matches_are_not_silently_grouped(self):
        for payload in [
            {"response": {"status": "NOT_FOUND"}},
            {"response": {"status": "OK", "result": {"featureCollection": {"features": []}}}},
            {"response": {"status": "OK", "result": {"featureCollection": {"features": [{}, {}]}}}},
        ]:
            with self.subTest(payload=payload):
                self.http.get.return_value = payload
                with self.assertRaises(InvalidWeatherQueryError):
                    self.resolver.resolve(self.location)

    def test_malformed_code_is_rejected_instead_of_used_as_a_cache_key(self):
        for code in ["9900", "990001", "ABCDE", 99001, None]:
            with self.subTest(code=code):
                self.http.get.return_value = boundary_response(code)
                with self.assertRaises(WeatherProviderDataError):
                    self.resolver.resolve(self.location)

    def test_provider_errors_do_not_expose_authentication_text(self):
        self.http.get.return_value = {"response": {"status": "ERROR", "error": {"text": "test-private-key"}}}
        with self.assertRaises(WeatherProviderUnavailableError) as caught:
            self.resolver.resolve(self.location)
        self.assertNotIn("test-private-key", str(caught.exception))
        self.http.get.side_effect = WeatherProviderDataError("private URL with test-private-key")
        with self.assertRaises(WeatherProviderUnavailableError) as caught:
            self.resolver.resolve(self.location)
        self.assertNotIn("test-private-key", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
