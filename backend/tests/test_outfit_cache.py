"""실제 외부 API 없이 영속 추천 캐시와 시간별 갱신을 검증한다."""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.common.config import get_settings
from app.common.database import connect_database
from app.outfits.application.exceptions import OutfitForecastError, OutfitLlmTimeoutError
from app.outfits.bootstrap import get_cached_outfit_service
from app.outfits.infrastructure.result_cache import CachedOutfitService, OutfitRefreshWorker
from main import app
from tests import test_outfits as fixtures


class OutfitCacheTests(unittest.TestCase):
    def setUp(self):
        """임시 DB와 고정 시계·모의 생성기 준비"""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "cache.db"
        self.fixture = fixtures.OutfitIntegrationTests()
        self.fixture.setUp()
        self.now = self.fixture.now
        self.service = Mock(wraps=self.fixture.service)
        self.factory = Mock(return_value=self.service)
        self.cache = self.make_cache()

    def make_cache(self, scope="test"):
        """서버 재시작과 모델 설정 변경을 재현할 저장소 구성"""
        return CachedOutfitService(self.database_path, scope, self.factory, 3600, lambda: self.now)

    def test_repeat_and_restart_reuse_persisted_result_without_weather_or_llm(self):
        """반복 조회와 새 인스턴스는 날씨·모델을 다시 호출하지 않는다."""
        first = self.cache.get_today(37, 127)
        self.assertEqual(self.cache.get_today(37, 127), first)
        self.assertEqual(self.make_cache().get_today(37, 127), first)
        self.factory.assert_called_once()
        self.fixture.llm.chat.assert_called_once()
        self.fixture.http.get.assert_called_once()

    def test_legacy_database_migrates_without_losing_results_or_other_tables(self):
        """요청 시각 컬럼이 없는 기존 DB도 저장 결과와 사용자 데이터를 유지한다."""
        first = self.cache.get_today(37, 127)
        with closing(connect_database(self.database_path)) as connection, connection:
            connection.execute("CREATE TABLE migration_sentinel (value TEXT)")
            connection.execute("INSERT INTO migration_sentinel VALUES ('keep')")
            connection.execute("ALTER TABLE outfit_result_cache DROP COLUMN requested_at")
        migrated = self.make_cache()
        migrated.refresh_due()
        self.assertEqual(migrated.get_today(37, 127), first)
        self.assertEqual(self.make_cache().get_today(37, 127), first)
        self.factory.assert_called_once()
        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute("SELECT requested_at, payload FROM outfit_result_cache").fetchone()
            self.assertEqual(row["requested_at"], self.now.timestamp())
            self.assertIsNotNone(row["payload"])
            self.assertEqual(connection.execute("SELECT value FROM migration_sentinel").fetchone()[0], "keep")
        self.now += timedelta(hours=1)
        migrated.refresh_due()
        self.assertEqual(self.factory.call_count, 2)

    def test_hourly_refresh_replaces_result_and_early_ticks_do_not_generate(self):
        """갱신 기한 전에는 생성하지 않고 한 시간 후 결과를 교체한다."""
        self.cache.get_today(37, 127)
        self.now += timedelta(seconds=3599)
        self.cache.refresh_due()
        self.assertEqual(self.factory.call_count, 1)
        self.now += timedelta(seconds=1)
        original = self.fixture.service.get_today(37, 127)
        replacement = replace(original, engine=replace(original.engine, model="refreshed-model"))
        self.service.get_today.return_value = replacement
        self.cache.refresh_due()
        self.assertEqual(self.cache.get_today(37, 127), replacement)
        self.assertEqual(self.factory.call_count, 2)
        self.cache.refresh_due()
        self.assertEqual(self.factory.call_count, 2)

    def test_refresh_failure_preserves_old_result_and_retries_only_next_hour(self):
        """갱신 오류가 기존 정상 결과를 지우거나 매분 재시도를 유발하지 않는다."""
        first = self.cache.get_today(37, 127)
        self.now += timedelta(hours=1)
        self.service.get_today.side_effect = OutfitLlmTimeoutError()
        with self.assertLogs("app.outfits.infrastructure.result_cache", level="WARNING"):
            self.cache.refresh_due()
        self.assertEqual(self.cache.get_today(37, 127), first)
        self.cache.refresh_due()
        self.assertEqual(self.factory.call_count, 2)
        self.now += timedelta(hours=1)
        with self.assertLogs("app.outfits.infrastructure.result_cache", level="WARNING"):
            self.cache.refresh_due()
        self.assertEqual(self.factory.call_count, 3)

    def test_expired_or_previous_day_results_are_not_served_as_current(self):
        """세 시간 초과 결과나 한국 날짜가 바뀐 결과는 재생성한다."""
        self.cache.get_today(37, 127)
        self.now += timedelta(hours=3, seconds=1)
        self.service.get_today.side_effect = OutfitLlmTimeoutError()
        with self.assertRaises(OutfitLlmTimeoutError):
            self.cache.get_today(37, 127)
        self.now = self.fixture.now + timedelta(days=1)
        with self.assertRaises(OutfitLlmTimeoutError):
            self.cache.get_today(37, 127)

    def test_modes_locations_and_model_scopes_do_not_share_results(self):
        """오늘·주간, 다른 좌표와 모델 설정을 별도 저장한다."""
        today = self.cache.get_today(37, 127)
        weekly = self.cache.get_weekly(37, 127)
        self.assertEqual(len(weekly.daily), 7)
        self.assertEqual(self.cache.get_weekly(37, 127), weekly)
        self.cache.get_today(38, 127)
        self.make_cache("different-model").get_today(37, 127)
        self.assertEqual(self.factory.call_count, 4)
        self.assertEqual(self.cache.get_today(37, 127), today)

    def test_concurrent_cold_requests_generate_once(self):
        """같은 지역을 동시에 처음 조회해도 중복 추론하지 않는다."""
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.cache.get_today(37, 127), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.factory.assert_called_once()

    def test_cached_reads_do_not_wait_for_an_in_progress_refresh(self):
        """긴 백그라운드 생성 중에도 기존 추천을 즉시 읽는다."""
        first = self.cache.get_today(37, 127)
        self.now += timedelta(hours=1)
        started, release = Event(), Event()

        def generate(latitude, longitude):
            started.set()
            if not release.wait(5):
                raise AssertionError("Refresh was not released")
            return first

        self.service.get_today.side_effect = generate
        with ThreadPoolExecutor(max_workers=2) as pool:
            refresh = pool.submit(self.cache.refresh_due)
            try:
                self.assertTrue(started.wait(2))
                read = pool.submit(self.cache.get_today, 37, 127)
                self.assertEqual(read.result(timeout=2), first)
            finally:
                release.set()
            refresh.result(timeout=2)

    def test_first_failure_is_not_cached_and_abandoned_regions_stop_refreshing(self):
        """최초 실패 결과는 저장하지 않고 24시간 미조회 지역은 갱신하지 않는다."""
        self.service.get_today.side_effect = OutfitLlmTimeoutError()
        with self.assertRaises(OutfitLlmTimeoutError):
            self.cache.get_today(37, 127)
        self.now += timedelta(hours=25)
        self.cache.refresh_due()
        self.factory.assert_called_once()

    def test_invalid_stored_json_is_replaced_and_old_date_generation_is_rejected(self):
        """손상된 저장값은 재생성하고 날짜가 지난 생성 결과는 저장하지 않는다."""
        self.cache.get_today(37, 127)
        with closing(connect_database(self.database_path)) as connection, connection:
            connection.execute("UPDATE outfit_result_cache SET payload='invalid'")
        self.cache.get_today(37, 127)
        self.assertEqual(self.factory.call_count, 2)
        self.now += timedelta(days=1)
        with self.assertRaises(OutfitForecastError):
            self.cache.get_today(37, 127)

    def test_worker_starts_and_stops_and_continues_after_tick_failure(self):
        """서버 작업 시작·종료와 갱신 오류 이후 생존 확인"""
        service = Mock()
        called = Event()

        def refresh(stopped):
            if service.refresh_due.call_count == 1:
                raise RuntimeError("temporary failure")
            called.set()
            stopped.set()

        service.refresh_due.side_effect = refresh
        worker = OutfitRefreshWorker(service)
        with patch.object(worker._stopped, "wait", return_value=False):
            with self.assertLogs("app.outfits.infrastructure.result_cache", level="WARNING"):
                worker.start()
                try:
                    self.assertTrue(called.wait(2))
                finally:
                    worker.stop()
        self.assertFalse(worker._thread.is_alive())

    def test_http_routes_use_cache_and_lifespan_manages_worker(self):
        """실제 HTTP 의존성 연결과 서버 수명의 작업 시작·종료를 검증한다."""
        with (
            patch.dict(app.dependency_overrides, {get_cached_outfit_service: lambda: self.cache}),
            patch("main.initialize_database"),
            patch("main.get_cached_outfit_service", return_value=self.cache),
            patch("main.OutfitRefreshWorker") as worker,
        ):
            with TestClient(app) as client:
                for kind in ["today", "weekly"]:
                    url = f"/api/v1/outfits/{kind}?latitude=37&longitude=127"
                    first = client.get(url)
                    second = client.get(url)
                    self.assertEqual(first.status_code, 200)
                    self.assertEqual(first.json(), second.json())
                worker.return_value.start.assert_called_once()
            worker.return_value.stop.assert_called_once()
        self.assertEqual(self.factory.call_count, 2)


class RefreshSettingsTests(unittest.TestCase):
    def test_refresh_interval_defaults_to_hourly_and_rejects_invalid_values(self):
        """기본 갱신 주기와 설정 범위를 확인한다."""
        with patch.dict(os.environ, {}, clear=True), patch("app.common.config.dotenv_values", return_value={}) as dotenv:
            get_settings.cache_clear()
            self.addCleanup(get_settings.cache_clear)
            self.assertEqual(get_settings().outfit_refresh_seconds, 3600)
            for value in ["0", "nan", "59", "86401"]:
                dotenv.return_value = {"STUDY_OUTFIT_REFRESH_SECONDS": value}
                get_settings.cache_clear()
                with self.subTest(value=value), self.assertRaises(ValueError):
                    get_settings()
