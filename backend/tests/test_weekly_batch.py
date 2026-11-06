"""오늘 문맥 분리와 야간 전용 주간 배치 정책의 회귀 검증."""

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from app.common.config import get_settings
from app.outfits.application.exceptions import OutfitLlmTimeoutError, WeeklyOutfitNotReadyError
from app.outfits.application.services.neighborhood_service import NeighborhoodOutfitService
from app.outfits.domain.preferences import OutfitPreferences, OutfitStyle
from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.personalized_cache import SQLitePersonalizedOutfitCache
from app.outfits.infrastructure.result_cache import CachedOutfitService
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

    def make_cache(self):
        return CachedOutfitService(
            self.database_path, "batch-test", self.factory, clock=lambda: self.fixture.now,
            reuse_unchanged_weather=True, weekly_batch_only=True,
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

    def test_batch_failure_keeps_old_result_and_does_not_retry_same_day(self):
        with self.assertRaises(WeeklyOutfitNotReadyError):
            self.cache.get_weekly(37, 127)
        self.at(1)
        self.cache.run_weekly_batch()
        first = self.cache.get_weekly(37, 127)
        self.at(1, days=1)
        self.cache.get_weekly(37, 127)
        self.fixture.llm.chat.side_effect = OutfitLlmTimeoutError()
        with self.assertLogs("app.outfits.infrastructure.result_cache", level="WARNING"):
            failed = self.cache.run_weekly_batch()
        self.assertEqual(failed["status"], "partial_failure")
        self.assertEqual(self.cache.run_weekly_batch()["status"], "already_run")
        self.assertEqual(self.cache.get_weekly(37, 127), first)

    def test_batch_only_starts_in_one_am_window(self):
        self.at(2)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "not_due")
        self.at(1, 59)
        self.assertEqual(self.cache.run_weekly_batch()["status"], "completed")

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
        service = NeighborhoodOutfitService(locations, self.cache, personal, regions)
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
    @patch("app.outfits.infrastructure.ollama_client.urlopen")
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
