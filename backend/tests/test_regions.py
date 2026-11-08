"""동네 공통 추천 재사용과 개인화·날씨 변경을 외부 호출 없이 검증한다."""

# 표준 라이브러리
import tempfile
import os
import json
from concurrent.futures import ThreadPoolExecutor
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

# 외부 라이브러리
from fastapi.testclient import TestClient

# 프로젝트 모듈
from app.common.database import connect_database
from app.common.config import get_settings
from app.outfits.application.exceptions import OutfitForecastError, OutfitLlmTimeoutError
from app.outfits.application.services import RegionOutfitService
from app.outfits.bootstrap import get_region_outfit_service
from app.outfits.domain.models import Activity, ColdSensitivity, OutfitPreferences, OutfitStyle
from app.outfits.infrastructure.recommenders import (
    LlmOutfitPersonalizer,
    PersonalizationChatClient,
    StructuredOutfitRecommender,
)
from app.outfits.infrastructure.cache import SQLitePersonalizedOutfitCache, CachedOutfitService
from app.weather.application.exceptions import InvalidWeatherQueryError
from app.weather.application.services import WeatherService
from app.weather.bootstrap import get_weather_service
from app.weather.domain.models import Location
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.location_catalog import SQLiteLocationCatalog
from app.weather.infrastructure.sigungu_resolver import VWorldSigunguResolver
from main import app
from tests import test_outfits as fixtures
from tests.test_weather import forecast_payload


class RegionTests(unittest.TestCase):
    def setUp(self):
        """검증용 지역·날씨·모델과 임시 저장소 준비"""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "regions.db"
        self.fixture = fixtures.OutfitIntegrationTests()
        self.fixture.setUp()
        self.fixture.weather_service._provider._cache = TTLCache(0)
        self.catalog = SQLiteLocationCatalog(self.database_path)
        self.location = Location(1001, "검증용 동네", 37, 127, "KR", admin1="검증용 상위 지역")
        self.catalog.save((self.location,))
        self.factory = Mock(return_value=self.fixture.service)
        self.cache = CachedOutfitService(
            self.database_path, "test", self.factory, clock=lambda: self.fixture.now,
            reuse_unchanged_weather=True,
        )
        self.region_http = Mock()
        self.region_http.get.return_value = {"response": {"status": "OK", "result": {"featureCollection": {
            "features": [{"properties": {"sig_cd": "99001", "sig_kor_nm": "검증용 시군구"}}],
        }}}}
        self.regions = VWorldSigunguResolver(
            self.database_path, "test-key", http=self.region_http, clock=lambda: self.fixture.now,
        )
        self.personal_llm = Mock()

        def personal_content(model, messages, schema):
            payload = json.loads(messages[1]["content"])
            generated = json.loads(fixtures.generated_content([day["date"] for day in payload["weather_days"]]))
            for day, weather in zip(generated["days"], payload["weather_days"]):
                day["best"]["top"] = f"{payload['preferences']['style']} 선택을 반영한 개인 상의"
                day["reasons"] = [f"최저 {weather['temperature_min_c']}도와 선택한 {payload['preferences']['activity']} 활동을 함께 고려한 생성 문장"]
            return json.dumps(generated, ensure_ascii=False)

        self.personal_llm.chat.side_effect = personal_content
        self.personalizer = LlmOutfitPersonalizer(lambda base, preferences: StructuredOutfitRecommender(
            PersonalizationChatClient(self.personal_llm, preferences), "test-personal-model", "ollama",
        ))
        self.personal_cache = SQLitePersonalizedOutfitCache(
            self.database_path, "personal-test", self.personalizer, self.cache, self.regions,
            clock=lambda: self.fixture.now,
        )
        self.service = RegionOutfitService(self.catalog, self.cache, self.personal_cache, self.regions)

    def test_different_preferences_share_one_generation_and_do_not_mutate_base(self):
        """동일 동네 사용자들의 취향 차이는 공통 결과·캐시 키를 오염시키지 않는다."""
        plain = self.service.get_today(1001, OutfitPreferences())
        personal = self.service.get_today(1001, OutfitPreferences(ColdSensitivity.COLD, OutfitStyle.FORMAL))
        again = self.service.get_today(1001, OutfitPreferences())
        self.assertEqual(again.result, plain.result)
        self.assertNotEqual(personal.result.recommendation.best, plain.result.recommendation.best)
        self.assertEqual(personal.result.base_version, plain.result.base_version)
        self.assertEqual(personal.result.generated_at, plain.result.generated_at)
        self.assertEqual(personal.result.recommendation.worst, plain.result.recommendation.worst)
        self.fixture.llm.chat.assert_called_once()
        self.factory.assert_called_once()
        with closing(connect_database(self.database_path)) as connection:
            rows = connection.execute("SELECT kind, latitude, longitude FROM outfit_result_cache").fetchall()
        self.assertEqual([tuple(row) for row in rows], [("region:99001:today", 37, 127)])
        self.personal_llm.chat.assert_called_once()

    def test_personal_cache_rejects_mismatched_result_kind_before_registration_or_inference(self):
        """오늘·주간 기본 결과를 잘못 전달하면 저장이나 모델 호출 전에 거부한다."""
        today = self.service.get_today(1001, OutfitPreferences()).result
        weekly = self.service.get_weekly(1001, OutfitPreferences()).result
        for kind, base in [("today", weekly), ("weekly", today), ("unknown", today)]:
            with self.subTest(kind=kind), self.assertRaises(OutfitForecastError):
                self.personal_cache.get(99001, kind, base, OutfitPreferences(style=OutfitStyle.FORMAL))
        self.personal_llm.chat.assert_not_called()
        with closing(connect_database(self.database_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM outfit_personal_targets").fetchone()[0]
        self.assertEqual(count, 0)

    def test_personal_cache_hashes_legacy_results_without_versions_for_both_kinds(self):
        """버전이 없는 기존 결과도 오늘·주간 타입별로 직렬화하고 캐시를 재사용한다."""
        for kind, base in [
            ("today", self.service.get_today(1001, OutfitPreferences()).result),
            ("weekly", self.service.get_weekly(1001, OutfitPreferences()).result),
        ]:
            with self.subTest(kind=kind):
                legacy = replace(base, base_version=None)
                preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
                first, first_hit = self.personal_cache.get(99001, kind, legacy, preferences)
                second, second_hit = self.personal_cache.get(99001, kind, legacy, preferences)
                self.assertFalse(first_hit)
                self.assertTrue(second_hit)
                self.assertEqual(first, second)
                self.assertEqual(len(first.base_version), 64)
        self.assertEqual(self.personal_llm.chat.call_count, 2)

    def test_weekly_personalization_rebuilds_wardrobe_without_an_extra_model_call(self):
        """개인화한 주간 의류 목록은 기본 준비물과 분리하고 추가 추론하지 않는다."""
        plain = self.service.get_weekly(1001, OutfitPreferences())
        personal = self.service.get_weekly(1001, OutfitPreferences(style=OutfitStyle.CASUAL, activity=Activity.ACTIVE))
        self.assertEqual(len(personal.result.daily), 7)
        self.assertNotEqual(personal.result.wardrobe, plain.result.wardrobe)
        self.assertEqual(personal.result.wardrobe.tops, tuple(dict.fromkeys(day.best.top for day in personal.result.daily)))
        self.assertEqual(personal.result.base_version, plain.result.base_version)
        self.fixture.llm.chat.assert_called_once()

    def test_catalog_persists_search_results_and_rejects_unknown_or_foreign_locations(self):
        """검색으로 검증한 국내 지역만 대표 위치로 재사용한다."""
        provider = Mock()
        other = replace(self.location, id=1002, name="다른 검증 지역")
        provider.search_locations.return_value = (other,)
        search = WeatherService(provider, self.catalog).search_locations("검증")
        self.assertEqual(search.locations, (other,))
        self.assertEqual(SQLiteLocationCatalog(self.database_path).get(1002), other)
        self.catalog.save((replace(other, id=1003, country_code="US"),))
        for location_id in [9999, 1003]:
            with self.subTest(location_id=location_id), self.assertRaises(InvalidWeatherQueryError):
                self.service.get_today(location_id, OutfitPreferences())
        self.factory.assert_not_called()

    def test_different_search_ids_in_same_sigungu_share_base_and_personal_generation(self):
        """서로 다른 검색 위치도 공식 시군구가 같으면 공통·개인 조건 캐시를 공유한다."""
        self.catalog.save((replace(self.location, id=1002, latitude=37.01),))
        first = self.service.get_today(1001, OutfitPreferences())
        second = self.service.get_today(1002, OutfitPreferences())
        self.assertEqual(first.result.base_version, second.result.base_version)
        self.assertEqual(first.region, second.region)
        self.assertEqual(second.result.forecast.coordinates, first.result.forecast.coordinates)
        self.service.get_today(1001, OutfitPreferences(style=OutfitStyle.FORMAL))
        personal = self.service.get_today(1002, OutfitPreferences(style=OutfitStyle.FORMAL))
        self.assertTrue(personal.personalization_cache_hit)
        self.fixture.llm.chat.assert_called_once()
        self.personal_llm.chat.assert_called_once()

    def test_unchanged_weather_updates_fetch_time_but_preserves_generation_and_version(self):
        """조회 시각만 바뀌면 최신 날씨를 저장하고 기존 모델 생성 버전을 유지한다."""
        first = self.service.get_today(1001, OutfitPreferences()).result
        self.fixture.now += timedelta(hours=1)
        self.cache.refresh_due()
        second = self.service.get_today(1001, OutfitPreferences()).result
        self.assertGreater(second.forecast.fetched_at, first.forecast.fetched_at)
        self.assertEqual(second.recommendation, first.recommendation)
        self.assertEqual(second.generated_at, first.generated_at)
        self.assertEqual(second.base_version, first.base_version)
        self.fixture.llm.chat.assert_called_once()

    def test_weather_value_change_regenerates_and_updates_base_version(self):
        """모델 입력값의 작은 변화도 보수적으로 재생성해 오래된 설명을 재사용하지 않는다."""
        first = self.service.get_today(1001, OutfitPreferences()).result
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 0.1
        self.fixture.now += timedelta(hours=1)
        self.cache.refresh_due()
        second = self.service.get_today(1001, OutfitPreferences()).result
        self.assertNotEqual(second.base_version, first.base_version)
        self.assertNotEqual(second.recommendation.weather, first.recommendation.weather)
        self.assertEqual(second.recommendation.weather, second.forecast.days[0])
        self.assertEqual(self.fixture.llm.chat.call_count, 2)

    def test_tomorrow_change_regenerates_weekly_but_not_today(self):
        """오늘과 주간은 실제 모델에 전달하는 날짜 범위로 변경 여부를 판단한다."""
        today = self.service.get_today(1001, OutfitPreferences()).result
        weekly = self.service.get_weekly(1001, OutfitPreferences()).result
        self.fixture.payload["daily"]["temperature_2m_max"][1] += 1
        self.fixture.now += timedelta(hours=1)
        self.cache.refresh_due()
        self.assertEqual(self.service.get_today(1001, OutfitPreferences()).result.base_version, today.base_version)
        self.assertNotEqual(self.service.get_weekly(1001, OutfitPreferences()).result.base_version, weekly.base_version)
        self.assertEqual(self.fixture.llm.chat.call_count, 3)

    def test_missing_weather_value_transition_triggers_regeneration(self):
        """기상 정보 없음과 실제 0은 같은 날씨로 취급하지 않는다."""
        first = self.service.get_today(1001, OutfitPreferences()).result
        self.fixture.payload["daily"]["precipitation_probability_max"][0] = None
        self.fixture.now += timedelta(hours=1)
        self.cache.refresh_due()
        second = self.service.get_today(1001, OutfitPreferences()).result
        self.assertNotEqual(second.base_version, first.base_version)
        self.assertIsNone(second.recommendation.weather.precipitation_probability_percent)
        self.assertEqual(self.fixture.llm.chat.call_count, 2)

    def test_failed_new_generation_preserves_previous_shared_result(self):
        """날씨 변경 후 새 추론이 실패해도 기존 공통 추천은 보존한다."""
        first = self.service.get_today(1001, OutfitPreferences()).result
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 1
        self.fixture.now += timedelta(hours=1)
        self.fixture.llm.chat.side_effect = OutfitLlmTimeoutError()
        with self.assertLogs("app.outfits.infrastructure.cache", level="WARNING"):
            self.cache.refresh_due()
        second = self.service.get_today(1001, OutfitPreferences()).result
        self.assertEqual(second, first)

    def test_new_korean_date_generates_a_new_version(self):
        """한국 날짜가 바뀌면 어제 공통 추천을 재사용하지 않는다."""
        first = self.service.get_today(1001, OutfitPreferences()).result
        self.fixture.now += timedelta(days=1)
        self.fixture.payload = forecast_payload(self.fixture.now)
        second = self.service.get_today(1001, OutfitPreferences()).result
        self.assertNotEqual(second.base_version, first.base_version)
        self.assertEqual(second.recommendation.date, second.forecast.today)
        self.assertEqual(self.fixture.llm.chat.call_count, 2)

    def test_shared_results_survive_restart_without_caching_personal_adjustments(self):
        """개인화 후 재시작해도 저장된 원본과 버전만 재사용한다."""
        first = self.service.get_today(1001, OutfitPreferences()).result
        self.service.get_today(1001, OutfitPreferences(style=OutfitStyle.FORMAL))
        cache = CachedOutfitService(
            self.database_path, "test", self.factory, clock=lambda: self.fixture.now,
            reuse_unchanged_weather=True,
        )
        restarted = RegionOutfitService(SQLiteLocationCatalog(self.database_path), cache, self.personal_cache, self.regions)
        self.assertEqual(restarted.get_today(1001, OutfitPreferences()).result, first)
        self.fixture.llm.chat.assert_called_once()

    def test_http_search_selection_and_personalized_responses(self):
        """지역 검색·선택·개인화 API 전체 흐름과 입력 검증을 확인한다."""
        provider = Mock()
        provider.search_locations.return_value = (self.location,)
        weather_service = WeatherService(provider, self.catalog)
        overrides = {
            get_region_outfit_service: lambda: self.service,
            get_weather_service: lambda: weather_service,
        }
        with patch.dict(app.dependency_overrides, overrides):
            client = TestClient(app)
            search = client.get("/api/v1/weather/locations?query=검증")
            self.assertEqual(search.status_code, 200)
            location_id = search.json()["data"]["locations"][0]["id"]
            url = f"/api/v1/outfits/regions/{location_id}/today"
            plain = client.get(url)
            personal = client.get(url + "?cold_sensitivity=cold&style=formal&activity=outdoor")
            self.assertEqual(plain.status_code, 200)
            self.assertEqual(personal.status_code, 200)
            data = personal.json()["data"]
            self.assertEqual(data["location"]["id"], location_id)
            self.assertEqual(data["coordinates"], {"latitude": 37, "longitude": 127})
            self.assertTrue(data["personalization"]["llm_used"])
            self.assertFalse(data["personalization"]["cache_hit"])
            self.assertEqual(data["region"]["code"], "99001")
            self.assertTrue(data["personalization"]["adjustments"])
            self.assertEqual(data["base_version"], plain.json()["data"]["base_version"])
            self.assertIsNotNone(data["generated_at"])
            self.assertEqual(client.get(url + "?style=unknown").status_code, 422)
            unknown = client.get("/api/v1/outfits/regions/9999/today")
            self.assertEqual(unknown.status_code, 422)
            self.assertEqual(unknown.json()["code"], "WEATHER_INVALID_QUERY")
            self.assertEqual(client.get("/api/v1/outfits/regions/0/today").status_code, 422)
            weekly = client.get(f"/api/v1/outfits/regions/{location_id}/weekly?activity=active")
            self.assertEqual(weekly.status_code, 200)
            self.assertEqual(len(weekly.json()["data"]["daily"]), 7)
        self.assertEqual(self.fixture.llm.chat.call_count, 2)


    def test_personal_narrative_is_generated_and_not_replaced_by_static_phrases(self):
        personal = self.service.get_today(1001, OutfitPreferences(style=OutfitStyle.FORMAL))
        self.assertIn("생성 문장", personal.result.recommendation.reasons[0])
        request = json.loads(self.personal_llm.chat.call_args.args[1][1]["content"])
        self.assertEqual(request["preferences"]["style"], "formal")
        self.assertIn("격식", request["personal_requirements"]["스타일"])
        self.assertEqual(request["output_schema"], self.personal_llm.chat.call_args.args[2])
        self.assertEqual(len(request["look_examples"]), 2)
        self.assertNotIn("shared_recommendations", request)
        self.assertEqual(personal.personalization.generated.engine.prompt_version, "2.5")

    def test_explicit_personal_conditions_have_distinct_meanings_without_changing_weather(self):
        """각 선택값의 의미를 명시하면서 원본 날씨와 출력 계약을 유지한다."""
        weather_inputs = []
        cases = [
            (OutfitPreferences(ColdSensitivity.COLD, OutfitStyle.FORMAL, Activity.OUTDOOR),
             ("추위를 많이", "격식", "야외")),
            (OutfitPreferences(ColdSensitivity.WARM, OutfitStyle.CASUAL, Activity.ACTIVE),
             ("더위를 많이", "캐주얼", "활발히")),
        ]
        for preferences, meanings in cases:
            with self.subTest(preferences=preferences):
                self.service.get_today(1001, preferences)
                _, messages, schema = self.personal_llm.chat.call_args.args
                request = json.loads(messages[1]["content"])
                requirements = request["personal_requirements"]
                for key, meaning in zip(("체온_성향", "스타일", "활동"), meanings):
                    self.assertIn(meaning, requirements[key])
                self.assertEqual(schema["properties"]["days"]["maxItems"], 1)
                weather_inputs.append(request["weather_days"])
        self.assertEqual(weather_inputs[0], weather_inputs[1])

    def test_personal_generation_is_reused_and_invalidated_when_base_changes(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        first = self.service.get_today(1001, preferences)
        second = self.service.get_today(1001, preferences)
        self.assertTrue(second.personalization_cache_hit)
        self.assertEqual(first.personalization, second.personalization)
        self.personal_llm.chat.assert_called_once()
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 1
        self.fixture.now += timedelta(hours=1)
        self.cache.refresh_due()
        third = self.service.get_today(1001, preferences)
        self.assertNotEqual(third.personalization.base_version, first.personalization.base_version)
        self.assertEqual(self.personal_llm.chat.call_count, 2)

    def test_personal_preparation_starts_ten_minutes_before_common_due_and_preserves_schedule(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        first = self.service.get_today(1001, preferences)
        initial = self.fixture.now
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 1
        self.fixture.now = initial + timedelta(minutes=49)
        self.personal_cache.refresh_due()
        self.personal_llm.chat.assert_called_once()
        self.fixture.now += timedelta(minutes=1)
        self.personal_cache.refresh_due()
        self.assertEqual(self.personal_llm.chat.call_count, 2)
        prepared = self.service.get_today(1001, preferences)
        self.assertTrue(prepared.personalization_cache_hit)
        self.assertNotEqual(prepared.result.base_version, first.result.base_version)
        self.fixture.now = initial + timedelta(hours=1)
        self.cache.refresh_due()
        self.assertEqual(self.fixture.llm.chat.call_count, 2)
        self.assertEqual(self.service.get_today(1001, preferences).personalization, prepared.personalization)
        with closing(connect_database(self.database_path)) as connection:
            attempted = connection.execute("SELECT attempted_at FROM outfit_result_cache").fetchone()[0]
        self.assertEqual(attempted, self.fixture.now.timestamp())

    def test_failed_personal_warmup_does_not_loop_or_cache_invalid_output(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        self.service.get_today(1001, preferences)
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 1
        self.personal_llm.chat.return_value = "invalid JSON"
        self.personal_llm.chat.side_effect = None
        self.fixture.now += timedelta(minutes=50)
        with self.assertLogs("app.outfits.infrastructure.cache", level="WARNING"):
            self.personal_cache.refresh_due()
        self.personal_cache.refresh_due()
        self.assertEqual(self.personal_llm.chat.call_count, 2)
        with closing(connect_database(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM outfit_personal_results").fetchone()[0], 1)

    def test_concurrent_personal_requests_generate_once(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        self.service.get_today(1001, OutfitPreferences())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.service.get_today(1001, preferences), range(4)))
        self.assertTrue(all(result.personalization == results[0].personalization for result in results))
        self.personal_llm.chat.assert_called_once()

    def test_personal_cache_survives_restart(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        first = self.service.get_today(1001, preferences)
        restarted_cache = SQLitePersonalizedOutfitCache(
            self.database_path, "personal-test", self.personalizer, self.cache, self.regions,
            clock=lambda: self.fixture.now,
        )
        restarted = RegionOutfitService(self.catalog, self.cache, restarted_cache, self.regions)
        second = restarted.get_today(1001, preferences)
        self.assertEqual(second.personalization, first.personalization)
        self.assertTrue(second.personalization_cache_hit)
        self.personal_llm.chat.assert_called_once()

    def test_failed_common_preparation_is_attempted_once_before_regular_refresh(self):
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        self.service.get_today(1001, preferences)
        self.fixture.payload["daily"]["temperature_2m_max"][0] += 1
        self.fixture.llm.chat.side_effect = OutfitLlmTimeoutError()
        self.fixture.now += timedelta(minutes=50)
        with self.assertLogs("app.outfits.infrastructure.cache", level="WARNING"):
            self.personal_cache.refresh_due()
        self.personal_cache.refresh_due()
        self.assertEqual(self.fixture.llm.chat.call_count, 2)
        self.personal_llm.chat.assert_called_once()

    def test_unchanged_base_requires_no_additional_personal_generation_during_preparation(self):
        self.service.get_today(1001, OutfitPreferences(style=OutfitStyle.FORMAL))
        self.fixture.now += timedelta(minutes=50)
        self.personal_cache.refresh_due()
        self.fixture.llm.chat.assert_called_once()
        self.personal_llm.chat.assert_called_once()

    def test_personal_preparation_does_not_extend_inactive_profile_lifetime(self):
        self.service.get_today(1001, OutfitPreferences(style=OutfitStyle.FORMAL))
        self.fixture.now += timedelta(minutes=50)
        self.personal_cache.refresh_due()
        self.fixture.now += timedelta(hours=24)
        self.personal_cache.refresh_due()
        self.personal_llm.chat.assert_called_once()


class SharedCapacitySettingsTests(unittest.TestCase):
    def test_shared_capacity_defaults_and_validation(self):
        """지역 공유 보관량을 설정할 수 있고 잘못된 용량은 거부한다."""
        with patch.dict(os.environ, {}, clear=True), patch("app.common.config.dotenv_values", return_value={}) as dotenv:
            get_settings.cache_clear()
            self.addCleanup(get_settings.cache_clear)
            self.assertEqual(get_settings().outfit_cache_max_entries, 4096)
            for raw in ["0", "100001", "2.5", "nan"]:
                dotenv.return_value = {"STUDY_OUTFIT_CACHE_MAX_ENTRIES": raw}
                get_settings.cache_clear()
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    get_settings()
