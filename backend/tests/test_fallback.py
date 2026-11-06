"""유료 호출 없이 로컬 우선 정책과 클라우드 자동 전환 확인."""

import os
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

from app.common.config import Settings, get_settings
from app.outfits.application.exceptions import (
    OutfitCloudRateLimitError, OutfitLlmModelNotFoundError, OutfitLlmNotConfiguredError,
    OutfitLlmResponseError, OutfitLlmTimeoutError, OutfitLlmUnavailableError,
)
from app.outfits.application.policies.fallback_recommender import FallbackOutfitRecommender
from app.outfits.application.services.outfit_service import OutfitService
from app.outfits.bootstrap import get_outfit_service
from app.outfits.infrastructure.gemini_recommender import GeminiOutfitRecommender
from app.outfits.presentation.router import get_today, get_weekly
from app.weather.application.exceptions import WeatherProviderTimeoutError
from tests import test_outfits as outfit_fixtures
from tests.test_gemini import gemini_response


class FallbackTests(unittest.TestCase):
    def setUp(self):
        """실제 날씨·LLM 통신을 대체한 추천 결과 준비"""
        fixture = outfit_fixtures.OutfitIntegrationTests()
        fixture.setUp()
        self.fixture = fixture
        self.forecast = fixture.reader.get_forecast(37, 127)
        self.local = Mock(return_value=fixture.recommender)
        self.cloud = Mock(return_value=GeminiOutfitRecommender(fixture.llm, "test-api-model"))
        self.recommender = FallbackOutfitRecommender(self.local, self.cloud)

    def test_local_success_never_constructs_or_calls_cloud(self):
        """로컬 성공 시 클라우드 설정과 호출을 건너뜀"""
        result = self.recommender.recommend(self.forecast.days[:1])
        self.assertEqual(result.engine.provider, "ollama")
        self.assertFalse(result.engine.fallback_used)
        self.assertIsNone(result.engine.fallback_reason)
        self.cloud.assert_not_called()

    def test_known_local_failures_use_cloud_once_with_original_weather(self):
        """로컬 설정·연결·시간·응답 오류에만 동일 날씨로 전환"""
        for error in [OutfitLlmNotConfiguredError, OutfitLlmModelNotFoundError, OutfitLlmUnavailableError,
                      OutfitLlmTimeoutError, OutfitLlmResponseError]:
            with self.subTest(error=error.__name__):
                self.local.side_effect = error()
                self.cloud.reset_mock()
                self.fixture.llm.chat.reset_mock()
                with self.assertLogs("app.outfits.application.policies.fallback_recommender", level="WARNING"):
                    result = self.recommender.recommend(self.forecast.days)
                self.assertEqual(result.engine.provider, "gemini")
                self.assertTrue(result.engine.fallback_used)
                self.assertEqual(result.engine.fallback_reason, error.error_code.value)
                self.assertEqual(tuple(item.weather for item in result.recommendations), self.forecast.days)
                self.cloud.assert_called_once_with()
                self.fixture.llm.chat.assert_called_once()

    def test_unexpected_errors_do_not_trigger_paid_fallback(self):
        """업무·프로그래밍 오류는 클라우드 호출 없이 전파"""
        for error in [ValueError("bug"), WeatherProviderTimeoutError()]:
            with self.subTest(error=type(error)):
                self.local.side_effect = error
                with self.assertRaises(type(error)):
                    self.recommender.recommend(self.forecast.days)
        self.cloud.assert_not_called()

    def test_cloud_failure_propagates_without_retrying_or_looping(self):
        """클라우드까지 실패하면 해당 오류를 반환하고 재시도하지 않음"""
        self.local.side_effect = OutfitLlmTimeoutError()
        cloud = Mock()
        cloud.recommend.side_effect = OutfitCloudRateLimitError()
        self.cloud.return_value = cloud
        with self.assertLogs("app.outfits.application.policies.fallback_recommender", level="WARNING"):
            with self.assertRaises(OutfitCloudRateLimitError):
                self.recommender.recommend(self.forecast.days)
        self.local.assert_called_once()
        self.cloud.assert_called_once()
        cloud.recommend.assert_called_once_with(self.forecast.days)

    def test_today_and_weekly_expose_actual_engine_in_common_response(self):
        """오늘·주간 API 모두 전환된 제공사와 이유를 직렬화"""
        local = Mock()
        local.recommend.side_effect = OutfitLlmTimeoutError()
        self.local.return_value = local
        service = OutfitService(self.fixture.reader, self.recommender)
        with self.assertLogs("app.outfits.application.policies.fallback_recommender", level="WARNING"):
            today = get_today(37, 127, service).model_dump(mode="json")
            weekly = get_weekly(37, 127, service).model_dump(mode="json")
        for response in [today, weekly]:
            self.assertEqual(response["code"], "SUCCESS")
            self.assertEqual(response["data"]["provider"], "Open-Meteo")
            engine = response["data"]["engine"]
            self.assertEqual(engine["provider"], "gemini")
            self.assertEqual(engine["model"], "test-api-model")
            self.assertTrue(engine["fallback_used"])
            self.assertEqual(engine["fallback_reason"], "OUTFIT_LLM_TIMEOUT")

    def test_weather_failure_stops_before_any_llm(self):
        """원본 예보 실패는 로컬·클라우드 생성 전에 종료"""
        reader = Mock()
        reader.get_forecast.side_effect = WeatherProviderTimeoutError()
        with self.assertRaises(WeatherProviderTimeoutError):
            OutfitService(reader, self.recommender).get_today(37, 127)
        self.local.assert_not_called()
        self.cloud.assert_not_called()

    def test_connection_failure_switches_real_clients_for_today_and_weekly(self):
        """로컬 연결 실패 시 실제 클라이언트 연결 흐름으로 클라우드 응답과 전환 정보를 확인한다."""
        settings = Settings(
            "test", Path("unused.db"), llm_model="local-model", cloud_fallback_enabled=True,
            gemini_api_key="test-key", gemini_model="cloud-model", fallback_local_timeout_seconds=180,
        )
        for route, days in [(get_today, self.forecast.days[:1]), (get_weekly, self.forecast.days)]:
            with (
                self.subTest(route=route.__name__),
                patch("app.outfits.bootstrap.get_settings", return_value=settings),
                patch("app.outfits.bootstrap.get_weather_service", return_value=self.fixture.weather_service),
                patch("app.outfits.infrastructure.ollama_client.urlopen", side_effect=URLError("connection refused")) as local,
                patch("app.outfits.infrastructure.gemini_client.genai.Client") as sdk,
            ):
                content = outfit_fixtures.generated_content([day.date.isoformat() for day in days])
                cloud = sdk.return_value.__enter__.return_value.models.generate_content
                cloud.return_value = gemini_response(content)
                with self.assertLogs("app.outfits.application.policies.fallback_recommender", level="WARNING"):
                    response = route(37, 127, get_outfit_service()).model_dump(mode="json")
                self.assertEqual(response["code"], "SUCCESS")
                engine = response["data"]["engine"]
                self.assertEqual(engine["provider"], "gemini")
                self.assertEqual(engine["model"], "cloud-model")
                self.assertTrue(engine["fallback_used"])
                self.assertEqual(engine["fallback_reason"], "OUTFIT_LLM_UNAVAILABLE")
                local.assert_called_once()
                self.assertEqual(local.call_args.kwargs["timeout"], 180)
                cloud.assert_called_once()

    @patch("app.outfits.bootstrap.get_weather_service")
    @patch("app.outfits.bootstrap.get_settings")
    @patch("app.outfits.bootstrap._cloud_recommender")
    @patch("app.outfits.bootstrap._local_recommender")
    def test_bootstrap_opt_in_selects_timeout_and_creates_cloud_lazily(self, local, cloud, settings, weather):
        """기본 로컬 전용과 명시적 전환 설정의 연결 정책 확인"""
        base = Settings("test", Path("unused.db"), llm_model="local")
        weather.return_value = self.fixture.weather_service
        for enabled, normal_timeout, fallback_timeout, expected_timeout in [
            (False, 180, None, 180), (False, 180, 15, 180),
            (True, 180, None, 180), (True, 300, None, 300), (True, 3, None, 3),
            (True, 180, 15, 15), (True, 3, 15, 3), (True, 180, 300, 180),
        ]:
            with self.subTest(enabled=enabled, timeout=normal_timeout, fallback_timeout=fallback_timeout):
                local.reset_mock()
                cloud.reset_mock()
                settings.return_value = replace(
                    base, cloud_fallback_enabled=enabled, llm_timeout_seconds=normal_timeout,
                    fallback_local_timeout_seconds=fallback_timeout,
                )
                local.return_value = self.fixture.recommender
                service = get_outfit_service()
                service.get_today(37, 127)
                local.assert_called_once_with(settings.return_value, expected_timeout)
                cloud.assert_not_called()


class CloudSettingsTests(unittest.TestCase):
    def setUp(self):
        """환경과 실제 키를 읽지 않는 설정 테스트 준비"""
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        dotenv = patch("app.common.config.dotenv_values", return_value={})
        self.dotenv = dotenv.start()
        self.addCleanup(dotenv.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_cloud_calls_are_disabled_by_default_without_a_selected_model(self):
        """자동 전환 기본 해제와 키·모델 미선택 확인"""
        settings = get_settings()
        self.assertFalse(settings.cloud_fallback_enabled)
        self.assertEqual(settings.gemini_api_key, "")
        self.assertEqual(settings.gemini_model, "")
        self.assertIsNone(settings.fallback_local_timeout_seconds)

    def test_fallback_timeout_is_optional_and_preserves_explicit_limits(self):
        """전환용 제한은 생략·빈 값이면 미설정, 명시한 값만 별도로 적용한다."""
        for raw, expected in [(None, None), ("", None), ("  ", None), ("15", 15), ("300", 300)]:
            with self.subTest(raw=raw):
                self.dotenv.return_value = {
                    "STUDY_LLM_TIMEOUT_SECONDS": "300",
                    "STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS": raw,
                }
                get_settings.cache_clear()
                settings = get_settings()
                self.assertEqual(settings.llm_timeout_seconds, 300)
                self.assertEqual(settings.fallback_local_timeout_seconds, expected)

    def test_dotenv_overrides_environment_and_hides_key_from_repr(self):
        """파일의 모델 우선 적용과 누락 항목의 환경변수 사용, 키 숨김 확인"""
        self.dotenv.return_value = {"STUDY_GEMINI_MODEL": " dotenv-model "}
        with patch.dict(os.environ, {"STUDY_LLM_CLOUD_FALLBACK_ENABLED": "true", "GEMINI_API_KEY": "test-secret",
                                    "STUDY_GEMINI_MODEL": " api-model ", "STUDY_GEMINI_MAX_OUTPUT_TOKENS": "4096"}):
            settings = get_settings()
        self.assertTrue(settings.cloud_fallback_enabled)
        self.assertEqual(settings.gemini_model, "dotenv-model")
        self.assertEqual(settings.gemini_max_output_tokens, 4096)
        self.assertNotIn("test-secret", repr(settings))

    def test_invalid_toggle_timeout_and_token_settings_are_rejected(self):
        """전환 여부·대기 시간·출력 상한의 잘못된 값 거부"""
        for key, value in [
            ("STUDY_LLM_CLOUD_FALLBACK_ENABLED", "yes"), ("STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS", "0"),
            ("STUDY_GEMINI_TIMEOUT_SECONDS", "nan"), ("STUDY_GEMINI_MAX_OUTPUT_TOKENS", "128.5"),
            ("STUDY_GEMINI_MAX_OUTPUT_TOKENS", "0"), ("STUDY_GEMINI_MAX_OUTPUT_TOKENS", "32769"),
        ]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                get_settings.cache_clear()
                with self.assertRaises(ValueError):
                    get_settings()
