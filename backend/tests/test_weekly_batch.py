"""오늘 문맥 분리와 야간 전용 주간 배치 정책의 회귀 검증."""

# 표준 라이브러리
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

# 프로젝트 모듈
from app.common.config import get_settings
from app.common.database import connect_database
from app.outfits.application.exceptions import OutfitLlmTimeoutError, WeeklyOutfitNotReadyError
from app.outfits.application.services import RegionOutfitService
from app.outfits.domain.models import OutfitPreferences, OutfitStyle
from app.outfits.infrastructure.clients import OllamaClient
from app.outfits.infrastructure.cache import SQLitePersonalizedOutfitCache, CachedOutfitService
from app.outfits.presentation.schemas import WeeklyOutfitResponse
from app.weather.domain.models import KST, Location, SigunguRegion
from app.weather.infrastructure.cache import TTLCache
from tests import test_outfits as fixtures
from tests.test_ollama import chat_envelope, http_response
from tests.test_weather import forecast_payload


class WeeklyBatchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "batch.db"
        self.fixture = fixtures.OutfitIntegrationTests()
        self.fixture.setUp()
        self.fixture.weather_service._provider._cache = TTLCache(0)
        self.at(0, 30)
        self.service = Mock(wraps=self.fixture.service)
        self.factory = Mock(return_value=self.service)
        self.cache = self.make_cache()

    def at(self, hour, minute=0, days=0):
        self.fixture.now = self.fixture.now.astimezone(KST).replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days)
        self.fixture.payload = forecast_payload(self.fixture.now)

    def make_cache(self, max_entries=128):
        return CachedOutfitService(
            self.database_path, "batch-test", self.factory, clock=lambda: self.fixture.now,
            reuse_unchanged_weather=True, weekly_batch_only=True, max_entries=max_entries,
        )

    def test_weekly_request_registers_target_but_never_generates_on_miss(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.factory.assert_not_called()
        self.assertEqual(self.cache.run_weekly_batch()["status"], "not_due")
        self.at(1)
        self.assertEqual(self.cache.run_weekly_batch()["generated"], 1)
        self.assertEqual(len(self.cache.get_weekly(37, 127).daily), 7)
        self.service.get_weekly.assert_called_once_with(37, 127)

    def test_today_regions_are_prepared_for_weekly_without_prior_weekly_request(self):
        self.cache.get_region_today(99001, 37, 127)
        self.at(1)
        self.assertEqual(self.cache.run_weekly_batch()["generated"], 1)
        self.assertEqual(len(self.cache.get_region_weekly(99001, 37, 127).daily), 7)

    def test_new_prompt_prepares_previous_weekly_targets_without_reusing_results(self):
        region_id = 99001
        preferences = (
            OutfitPreferences(style=OutfitStyle.FORMAL), OutfitPreferences(style=OutfitStyle.CASUAL),
        )
        old_personalizer = Mock()
        old_personalizer.personalize.side_effect = lambda base, conditions: base
        old_personal = SQLitePersonalizedOutfitCache(
            self.database_path, "personal-old", old_personalizer, self.cache, Mock(),
            clock=lambda: self.fixture.now, weekly_batch_only=True,
        )
        for conditions in preferences:
            old_personal.register(region_id, "weekly", conditions)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_region_weekly(region_id, 37, 127)
        self.at(1)
        self.assertEqual(self.cache.run_weekly_batch(on_ready=old_personal.prepare_weekly)["personalized_generated"], 2)

        self.at(2)
        new_cache = CachedOutfitService(
            self.database_path, "batch-upgraded", self.factory, clock=lambda: self.fixture.now,
            reuse_unchanged_weather=True, weekly_batch_only=True, previous_scope="batch-test",
        )
        new_personalizer = Mock()
        new_personalizer.personalize.side_effect = lambda base, conditions: base
        new_personal = SQLitePersonalizedOutfitCache(
            self.database_path, "personal-new", new_personalizer, new_cache, Mock(),
            clock=lambda: self.fixture.now, weekly_batch_only=True, previous_scope="personal-old",
        )
        new_personal.register(region_id, "weekly", preferences[0])
        result = new_cache.run_weekly_batch(on_ready=new_personal.prepare_weekly)

        self.assertEqual((result["status"], result["generated"], result["personalized_generated"]), ("completed", 1, 2))
        self.assertEqual(self.service.get_weekly.call_count, 2)
        self.assertCountEqual([call.args[1] for call in new_personalizer.personalize.call_args_list], preferences)
        common = new_cache.get_region_weekly(region_id, 37, 127)
        self.assertTrue(new_personal.get(region_id, "weekly", common, preferences[1], register=False)[1])

    def test_daily_claim_survives_restarts_and_prevents_duplicate_start(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "completed")
        self.assertEqual(self.cache.run_weekly_batch()["status"], "already_run")
        self.assertEqual(self.make_cache().run_weekly_batch()["status"], "already_run")
        self.service.get_weekly.assert_called_once()

    def test_concurrent_daily_jobs_only_claim_once(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        other = self.make_cache()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda cache: cache.run_weekly_batch(), [self.cache, other]))
        self.assertEqual({result["status"] for result in results}, {"completed", "already_run"})
        self.service.get_weekly.assert_called_once()

    def test_hourly_weather_checks_do_not_regenerate_weekly(self):
        self.cache.get_today(37, 127)
        self.at(1)
        self.cache.run_weekly_batch()
        first = self.cache.get_weekly(37, 127)
        self.at(6)
        self.fixture.payload["daily"]["temperature_2m_max"][1] += 2
        self.cache.refresh_due()
        self.assertEqual(self.cache.get_weekly(37, 127), first)
        self.service.get_weekly.assert_called_once()
        self.service.refresh_weekly.assert_not_called()

    def test_unchanged_today_weather_reuses_generation_and_changed_weather_regenerates(self):
        first = self.cache.get_today(37, 127)
        self.at(1, 30)
        self.cache.refresh_due()
        same = self.cache.get_today(37, 127)
        self.assertEqual(first.base_version, same.base_version)
        self.fixture.llm.chat.assert_called_once()
        self.at(2, 30)
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 1
        self.cache.refresh_due()
        self.assertNotEqual(self.cache.get_today(37, 127).base_version, same.base_version)
        self.assertEqual(self.fixture.llm.chat.call_count, 2)

    def test_previous_batch_remains_available_across_midnight_and_reports_original_date(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        self.cache.run_weekly_batch()
        first = self.cache.get_weekly(37, 127)
        self.at(0, 15, days=1)
        stored = self.cache.get_weekly(37, 127)
        self.assertEqual(stored.base_version, first.base_version)
        self.assertEqual(WeeklyOutfitResponse.from_result(stored).forecast_start_date, first.forecast.today)
        self.assertNotEqual(stored.forecast.today, self.fixture.now.date())
        self.service.get_weekly.assert_called_once()

    def test_expired_weekly_result_reports_not_ready_without_foreground_inference(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        self.cache.run_weekly_batch()
        self.at(2, days=2)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.service.get_weekly.assert_called_once()

    def test_batch_retries_transient_failure_with_backoff_then_stops_at_limit(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        self.cache.run_weekly_batch()
        first = self.cache.get_weekly(37, 127)
        self.at(1, days=1)
        self.cache.get_weekly(37, 127)
        self.fixture.llm.chat.side_effect = OutfitLlmTimeoutError()
        with self.assertLogs("app.outfits.infrastructure.cache", level="WARNING"):
            self.assertEqual(self.cache.run_weekly_batch()["status"], "retry_wait")
            self.at(1, 4)
            self.assertEqual(self.make_cache().run_weekly_batch()["generated"], 0)
            self.at(1, 5)
            self.assertEqual(self.make_cache().run_weekly_batch()["failed"], 1)
            self.at(1, 19)
            self.assertEqual(self.cache.run_weekly_batch()["failed"], 0)
            self.at(1, 20)
            self.assertEqual(self.cache.run_weekly_batch()["status"], "partial_failure")
        self.at(2)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "already_run")
        self.assertEqual(self.cache.get_weekly(37, 127), first)
        self.assertEqual(self.fixture.llm.chat.call_count, 4)

    def test_missed_schedule_is_caught_up_after_a_late_start(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(0, 59)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "not_due")
        self.at(10)
        self.assertEqual(self.make_cache().run_weekly_batch()["generated"], 1)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "already_run")

    def test_batch_without_targets_can_start_when_first_request_registers_one(self):
        self.at(10)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "no_targets")
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.assertEqual(self.cache.run_weekly_batch()["generated"], 1)

    def test_stopped_batch_resumes_without_regenerating_a_saved_common_result(self):
        for latitude in (37, 38):
            with self.assertRaises(WeeklyOutfitNotReadyError):
                self.cache.get_weekly(latitude, 127)
        self.at(1)
        stop = Event()

        def stop_after_common(key, base, stopped, *, check_lease):
            stop.set()

        result = self.cache.run_weekly_batch(stopped=stop, on_ready=stop_after_common)
        self.assertEqual((result["status"], result["generated"]), ("stopped", 1))
        self.assertEqual(len(self.cache.get_weekly(37, 127).daily), 7)
        restarted = self.make_cache().run_weekly_batch()
        self.assertEqual((restarted["status"], restarted["generated"]), ("completed", 1))
        self.assertEqual(self.service.get_weekly.call_count, 2)

    def test_full_cache_keeps_weekly_rows_even_when_a_target_was_requested_earlier(self):
        cache = self.make_cache(max_entries=2)
        cache.get_region_today(1001, 37, 127)
        self.at(0, 45)
        cache.get_region_today(1002, 38, 127)

        self.at(1)
        result = cache.run_weekly_batch()

        self.assertEqual((result["status"], result["generated"]), ("completed", 2))
        self.assertEqual(len(cache.get_region_weekly(1001, 37, 127).daily), 7)
        self.assertEqual(len(cache.get_region_weekly(1002, 38, 127).daily), 7)

    def test_request_pruning_keeps_the_saved_weekly_row_for_a_stopped_batch(self):
        cache = self.make_cache(max_entries=1)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            cache.get_region_weekly(1001, 37, 127)
        self.at(1)
        stop = Event()

        def stop_after_common(key, base, stopped, *, check_lease):
            stop.set()

        self.assertEqual(cache.run_weekly_batch(stopped=stop, on_ready=stop_after_common)["status"], "stopped")
        self.at(1, 1)
        cache.get_region_today(1002, 38, 127)

        resumed = self.make_cache(max_entries=1).run_weekly_batch()
        self.assertEqual((resumed["status"], resumed["generated"]), ("completed", 0))
        self.assertEqual(len(cache.get_region_weekly(1001, 37, 127).daily), 7)
        self.service.get_weekly.assert_called_once()

    def test_expired_run_lease_recovers_remaining_targets_after_abrupt_exit(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        status, run, targets = self.cache._weekly_batch.claim(self.fixture.now)
        self.assertEqual(status, "running")
        self.assertIsNotNone(run)
        self.assertEqual(len(targets), 1)
        self.at(1, 4)
        self.assertEqual(self.make_cache().run_weekly_batch()["status"], "already_run")
        self.at(1, 5)
        self.assertEqual(self.make_cache().run_weekly_batch()["generated"], 1)
        self.service.get_weekly.assert_called_once()

    def test_legacy_running_batch_is_recovered_when_sqlite_schema_is_upgraded(self):
        database_path = self.database_path.with_name("legacy.db")
        self.at(1)
        with closing(connect_database(database_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE outfit_weekly_batch_runs "
                "(scope TEXT NOT NULL, run_date TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, "
                "status TEXT NOT NULL, PRIMARY KEY(scope, run_date))",
            )
            connection.execute(
                "INSERT INTO outfit_weekly_batch_runs (scope, run_date, started_at, status) VALUES (?, ?, ?, 'running')",
                ("batch-test", self.fixture.now.date().isoformat(), self.fixture.now.timestamp()),
            )
        self.database_path = database_path
        cache = self.make_cache()
        with self.assertRaises(WeeklyOutfitNotReadyError):
            cache.get_weekly(37, 127)
        self.at(2)
        recovered = self.make_cache().run_weekly_batch()
        self.assertEqual((recovered["status"], recovered["generated"]), ("completed", 1))
        self.assertEqual(cache.run_weekly_batch()["status"], "already_run")

    def test_personal_retry_reuses_successful_common_and_personal_results(self):
        preferences = (
            OutfitPreferences(style=OutfitStyle.FORMAL), OutfitPreferences(style=OutfitStyle.CASUAL),
        )
        personalizer = Mock()
        calls = []

        def personalize(base, conditions):
            calls.append(conditions)
            if conditions == preferences[1] and calls.count(conditions) == 1:
                raise OutfitLlmTimeoutError()
            return base

        personalizer.personalize.side_effect = personalize
        personal = SQLitePersonalizedOutfitCache(
            self.database_path, "personal", personalizer, self.cache, Mock(),
            clock=lambda: self.fixture.now, weekly_batch_only=True,
        )
        for conditions in preferences:
            personal.register(1001, "weekly", conditions)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_region_weekly(1001, 37, 127)
        self.at(1)
        with self.assertLogs("app.outfits.infrastructure.cache", level="WARNING"):
            first = self.cache.run_weekly_batch(on_ready=personal.prepare_weekly)
        self.assertEqual((first["status"], first["generated"], first["personalized_generated"]), ("retry_wait", 1, 1))
        self.at(1, 5)
        resumed = self.make_cache().run_weekly_batch(on_ready=personal.prepare_weekly)
        self.assertEqual(
            (resumed["status"], resumed["generated"], resumed["personalized_generated"]), ("completed", 0, 1),
        )
        self.assertEqual([calls.count(conditions) for conditions in preferences], [1, 2])
        self.service.get_weekly.assert_called_once()

    def test_expired_worker_cannot_overwrite_personal_recommendation_after_takeover(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        new_cache = self.make_cache()
        new_personalizer = Mock()
        new_personalizer.personalize.side_effect = lambda base, conditions: base
        new_personal = SQLitePersonalizedOutfitCache(
            self.database_path, "personal", new_personalizer, new_cache, Mock(),
            clock=lambda: self.fixture.now, weekly_batch_only=True,
        )
        valid_result = []

        def complete_with_replacement_worker(base, conditions):
            self.at(1, 5)
            restarted = new_cache.run_weekly_batch(on_ready=new_personal.prepare_weekly)
            self.assertEqual(restarted["status"], "completed")
            common = new_cache.get_region_weekly(1001, 37, 127)
            valid_result.append(new_personal.get(1001, "weekly", common, conditions, register=False)[0])
            return base

        old_personalizer = Mock()
        old_personalizer.personalize.side_effect = complete_with_replacement_worker
        old_personal = SQLitePersonalizedOutfitCache(
            self.database_path, "personal", old_personalizer, self.cache, Mock(),
            clock=lambda: self.fixture.now, weekly_batch_only=True,
        )
        old_personal.register(1001, "weekly", preferences)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_region_weekly(1001, 37, 127)

        self.at(1)
        result = self.cache.run_weekly_batch(on_ready=old_personal.prepare_weekly)

        self.assertEqual(result["status"], "lease_lost")
        common = new_cache.get_region_weekly(1001, 37, 127)
        saved, cached = new_personal.get(1001, "weekly", common, preferences, register=False)
        self.assertTrue(cached)
        self.assertEqual(saved, valid_result[0])

    def test_weekly_personal_conditions_wait_for_batch_and_do_not_enter_hourly_preparation(self):
        regions = Mock()
        regions.resolve.return_value = SigunguRegion("99001", "검증 시군구", 37, 127)
        locations = Mock()
        locations.get.return_value = Location(1001, "검증 위치", 37, 127, "KR")
        personalizer = Mock()
        personalizer.personalize.side_effect = lambda base, preferences: base
        personal = SQLitePersonalizedOutfitCache(
            self.database_path, "personal", personalizer, self.cache, regions,
            clock=lambda: self.fixture.now, weekly_batch_only=True,
        )
        service = RegionOutfitService(locations, self.cache, personal, regions)
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            service.get_weekly(1001, preferences)
        personalizer.personalize.assert_not_called()
        self.factory.assert_not_called()
        self.at(1)
        result = self.cache.run_weekly_batch(on_ready=personal.prepare_weekly)
        self.assertEqual(result["personalized_generated"], 1)
        self.assertTrue(service.get_weekly(1001, preferences).personalization_cache_hit)
        personalizer.personalize.assert_called_once()
        self.at(12)
        with self.assertRaises(WeeklyOutfitNotReadyError):
            service.get_weekly(1001, OutfitPreferences(style=OutfitStyle.CASUAL))
        personal.refresh_due()
        personalizer.personalize.assert_called_once()


class TodayContextTests(unittest.TestCase):
    @patch("app.outfits.infrastructure.clients.urlopen")
    def test_today_uses_4096_and_weekly_preserves_general_context(self, urlopen):
        import json

        urlopen.return_value = http_response(chat_envelope())
        client = OllamaClient("http://localhost:11434", 180, 16384, today_context_size=4096)
        client.chat("model", [], {"properties": {"days": {"maxItems": 1}}})
        options = json.loads(urlopen.call_args.args[0].data)["options"]
        self.assertEqual(options["num_ctx"], 4096)
        self.assertEqual(options["num_predict"], 2048)
        client.chat("model", [], {"properties": {"days": {"maxItems": 7}}})
        options = json.loads(urlopen.call_args.args[0].data)["options"]
        self.assertEqual(options["num_ctx"], 16384)
        self.assertEqual(options["num_predict"], 8192)

    def test_schedule_and_today_context_settings_are_validated(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.common.config.dotenv_values", return_value={}) as dotenv:
            get_settings.cache_clear()
            self.addCleanup(get_settings.cache_clear)
            settings = get_settings()
            self.assertEqual(settings.llm_today_context_size, 4096)
            self.assertEqual(settings.outfit_weekly_batch_hour, 1)
            for key, value in [
                ("STUDY_LLM_TODAY_CONTEXT_SIZE", "0"), ("STUDY_OUTFIT_WEEKLY_BATCH_HOUR", "24"),
                ("STUDY_OUTFIT_WEEKLY_MAX_AGE_SECONDS", "0"),
            ]:
                dotenv.return_value = {key: value}
                get_settings.cache_clear()
                with self.subTest(key=key), self.assertRaises(ValueError):
                    get_settings()
