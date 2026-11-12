"""유료 호출 없이 로컬 우선 정책과 클라우드 자동 전환 확인."""

# 표준 라이브러리
import json
import io
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

# 프로젝트 모듈
from app.common.config import Settings, get_settings
from app.outfits.application.exceptions import (
    OutfitCloudRateLimitError,
    OutfitLlmModelNotFoundError,
    OutfitLlmNotConfiguredError,
    OutfitLlmResponseError,
    OutfitLlmTimeoutError,
    OutfitLlmUnavailableError,
)
from app.outfits.application.policies import FallbackOutfitRecommender
from app.outfits.application.services import OutfitService
from app.outfits.bootstrap import _personal_recommender, get_outfit_service
from app.outfits.feedback_bootstrap import feedback_store_for_path
from app.outfits.domain.models import OutfitPreferences, OutfitStyle
from app.outfits.infrastructure.prompts import PERSONALIZATION_VERSION
from app.outfits.infrastructure.recommenders import GeminiOutfitRecommender, LlmOutfitPersonalizer
from app.outfits.presentation.router import get_today, get_weekly
from app.weather.application.exceptions import WeatherProviderTimeoutError
from tests import test_outfits as outfit_fixtures
from tests.test_gemini import gemini_response
from tests.test_ollama import chat_envelope, http_response


class FallbackTests(unittest.TestCase):
    def setUp(self):
        """실제 날씨·LLM 통신을 대체한 추천 결과 준비"""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database_path = Path(directory.name) / "fallback.db"
        self.addCleanup(feedback_store_for_path.cache_clear)
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
                with self.assertLogs("app.outfits.application.policies", level="WARNING"):
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
        with self.assertLogs("app.outfits.application.policies", level="WARNING"):
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
        with self.assertLogs("app.outfits.application.policies", level="WARNING"):
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
            "test", self.database_path, llm_model="local-model", cloud_fallback_enabled=True,
            gemini_api_key="test-key", gemini_model="cloud-model", fallback_local_timeout_seconds=180,
        )
        for route, days in [(get_today, self.forecast.days[:1]), (get_weekly, self.forecast.days)]:
            with (
                self.subTest(route=route.__name__),
                patch("app.outfits.bootstrap.get_settings", return_value=settings),
                patch("app.outfits.bootstrap.get_weather_service", return_value=self.fixture.weather_service),
                patch("app.outfits.infrastructure.clients.urlopen", side_effect=URLError("connection refused")) as local,
                patch("app.outfits.infrastructure.clients.genai.Client") as sdk,
            ):
                content = outfit_fixtures.generated_content([day.date.isoformat() for day in days])
                cloud = sdk.return_value.__enter__.return_value.models.generate_content
                cloud.return_value = gemini_response(content)
                with self.assertLogs("app.outfits.application.policies", level="WARNING"):
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
        base = Settings("test", self.database_path, llm_model="local")
        weather.return_value = self.fixture.weather_service
        for enabled, normal_timeout, fallback_timeout, expected_timeout in [
            (False, 180, None, 180), (False, 180, 15, 180),
            (True, 180, None, 20), (True, 300, None, 20), (True, 3, None, 3),
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

    def test_personal_local_requests_keep_preferences_options_and_timeout_without_cloud(self):
        """개인화에서도 설정한 문맥·샘플링·대기 제한과 조건을 전달하고 유료 호출을 생략한다."""
        base = self.fixture.recommender.recommend(self.forecast.days[:1])
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        content = outfit_fixtures.generated_content([self.forecast.days[0].date.isoformat()])
        for enabled, fallback_timeout, expected_timeout in [(False, 15, 180), (True, 15, 15), (True, 300, 180)]:
            settings = Settings(
                "test", self.database_path, llm_model="local-model", cloud_fallback_enabled=enabled,
                fallback_local_timeout_seconds=fallback_timeout, llm_thinking=False, llm_top_p=0.8, llm_min_p=0,
            )
            with (
                self.subTest(enabled=enabled, fallback_timeout=fallback_timeout),
                patch("app.outfits.bootstrap.get_settings", return_value=settings),
                patch("app.outfits.infrastructure.clients.urlopen", return_value=http_response(chat_envelope(content))) as local,
                patch("app.outfits.bootstrap.GeminiClient") as cloud,
            ):
                result = LlmOutfitPersonalizer(_personal_recommender).personalize(base, preferences)
                payload = json.loads(local.call_args.args[0].data)
                self.assertEqual(local.call_args.kwargs["timeout"], expected_timeout)
                self.assertEqual(payload["options"], {
                    "temperature": 0.3, "top_p": 0.8, "min_p": 0, "num_predict": 2048, "num_ctx": 4096,
                })
                self.assertFalse(payload["think"])
                self.assertEqual(json.loads(payload["messages"][1]["content"])["preferences"]["style"], "formal")
                self.assertEqual(result.engine.prompt_version, PERSONALIZATION_VERSION)
                self.assertFalse(result.engine.fallback_used)
                cloud.assert_not_called()

    def test_personal_local_failure_calls_cloud_once_with_preferences_and_fallback_metadata(self):
        """로컬 개인화 실패 시 같은 조건을 SDK로 한 번 전달하고 전환 정보를 보존한다."""
        base = self.fixture.recommender.recommend(self.forecast.days[:1])
        preferences = OutfitPreferences(style=OutfitStyle.FORMAL)
        settings = Settings(
            "test", self.database_path, llm_model="local-model", cloud_fallback_enabled=True,
            gemini_api_key="test-key", gemini_model="cloud-model", fallback_local_timeout_seconds=15,
        )
        with (
            patch("app.outfits.bootstrap.get_settings", return_value=settings),
            patch("app.outfits.infrastructure.clients.urlopen", side_effect=URLError("connection refused")) as local,
            patch("app.outfits.infrastructure.clients.genai.Client") as sdk,
        ):
            cloud = sdk.return_value.__enter__.return_value.models.generate_content
            cloud.return_value = gemini_response(outfit_fixtures.generated_content([self.forecast.days[0].date.isoformat()]))
            with self.assertLogs("app.outfits.application.policies", level="WARNING"):
                result = LlmOutfitPersonalizer(_personal_recommender).personalize(base, preferences)
            local.assert_called_once()
            self.assertEqual(local.call_args.kwargs["timeout"], 15)
            cloud.assert_called_once()
            content = json.loads(cloud.call_args.kwargs["contents"][0].parts[0].text)
            self.assertEqual(content["preferences"]["style"], "formal")
            self.assertEqual(result.recommendations[0].weather, base.recommendations[0].weather)
            self.assertEqual(result.engine.provider, "gemini")
            self.assertEqual(result.engine.model, "cloud-model")
            self.assertEqual(result.engine.prompt_version, PERSONALIZATION_VERSION)
            self.assertTrue(result.engine.fallback_used)
            self.assertEqual(result.engine.fallback_reason, "OUTFIT_LLM_UNAVAILABLE")

    def test_local_repair_preserves_both_attempts_and_final_generation_without_cloud(self):
        """공통·개인화의 검증 실패나 시간 초과 후 로컬 재시도와 생성 기록을 검증한다."""
        days = self.forecast.days[:1]
        content = outfit_fixtures.generated_content([days[0].date.isoformat()])
        base = self.fixture.recommender.recommend(days)
        for preferences in (None, OutfitPreferences(style=OutfitStyle.FORMAL)):
            for failure in ("schema", "date", "quality", "duplicate", "timeout"):
                invalid = json.loads(content)
                if failure == "schema":
                    del invalid["days"][0]["best"]["shoes"]
                elif failure == "date":
                    invalid["days"][0]["date"] = "2000-01-01"
                elif failure == "quality":
                    invalid["days"][0]["best"]["shoes"] = "장갑"
                elif failure == "duplicate":
                    best = invalid["days"][0]["best"]
                    invalid["days"][0]["worst"] = {
                        **best, "accessories": best["accessories"] * 2,
                    }
                first_attempt = (
                    TimeoutError() if failure == "timeout"
                    else http_response(chat_envelope(json.dumps(invalid, ensure_ascii=False)))
                )
                path = self.database_path.with_name(f"repair-{preferences is not None}-{failure}.db")
                settings = Settings("test", path, llm_model="local-model", cloud_fallback_enabled=True)
                with (
                    self.subTest(personal=preferences is not None, failure=failure),
                    patch("app.outfits.bootstrap.get_settings", return_value=settings),
                    patch("app.outfits.bootstrap.get_weather_service", return_value=self.fixture.weather_service),
                    patch("app.outfits.infrastructure.clients.urlopen", side_effect=[
                        first_attempt,
                        http_response(chat_envelope(content)),
                    ]) as local,
                    patch("app.outfits.infrastructure.clients.genai.Client") as cloud,
                ):
                    result = (
                        get_outfit_service().get_today(37, 127) if preferences is None
                        else LlmOutfitPersonalizer(_personal_recommender).personalize(base, preferences)
                    )
                    self.assertEqual(local.call_count, 2)
                    self.assertEqual([call.kwargs["timeout"] for call in local.call_args_list], [20, 20])
                    cloud.assert_not_called()
                    first, second = [json.loads(call.args[0].data) for call in local.call_args_list]
                    self.assertNotIn("answer_checks", json.loads(first["messages"][1]["content"]))
                    corrected_request = json.loads(second["messages"][1]["content"])
                    if failure == "timeout":
                        self.assertEqual(first, second)
                    else:
                        self.assertIn("answer_checks", corrected_request)
                    if failure == "duplicate":
                        self.assertIn("서로 다른 옷차림", corrected_request["answer_checks"][0])
                    if preferences is not None:
                        self.assertEqual(corrected_request["preferences"]["style"], "formal")
                    store = feedback_store_for_path(path)
                    self.assertEqual(len(store.generations()), 2)
                    generation = store.generation(result.engine.generation_id)
                    self.assertEqual(generation["raw_response"], content)
                    self.assertEqual(generation["provider"], "ollama")
                    self.assertFalse(result.engine.fallback_used)

    def test_local_transport_failures_record_cloud_generation_and_allow_feedback(self):
        """연결 실패·500·404·시간 초과 후 Gemini로 한 번 전환하고 원본 ID로 신고할 수 있다."""
        days = self.forecast.days[:1]
        content = outfit_fixtures.generated_content([days[0].date.isoformat()])
        base = self.fixture.recommender.recommend(days)
        cases = [
            (lambda: URLError(ConnectionRefusedError()), "OUTFIT_LLM_UNAVAILABLE"),
            (lambda: HTTPError("http://local/api/chat", 500, "failed", {}, io.BytesIO()), "OUTFIT_LLM_UNAVAILABLE"),
            (lambda: HTTPError("http://local/api/chat", 404, "missing", {}, io.BytesIO()), "OUTFIT_LLM_MODEL_NOT_FOUND"),
            (TimeoutError, "OUTFIT_LLM_TIMEOUT"),
        ]
        for personal in (False, True):
            for index, (failure, reason) in enumerate(cases):
                path = self.database_path.with_name(f"transport-{personal}-{index}.db")
                settings = Settings(
                    "test", path, llm_model="local-model", cloud_fallback_enabled=True,
                    gemini_api_key="test-key", gemini_model="cloud-model",
                )
                with (
                    self.subTest(personal=personal, reason=reason, case=index),
                    patch("app.outfits.bootstrap.get_settings", return_value=settings),
                    patch("app.outfits.bootstrap.get_weather_service", return_value=self.fixture.weather_service),
                    patch("app.outfits.infrastructure.clients.urlopen", side_effect=failure()) as local,
                    patch("app.outfits.infrastructure.clients.genai.Client") as sdk,
                ):
                    cloud = sdk.return_value.__enter__.return_value.models.generate_content
                    local_attempts = 2 if reason == "OUTFIT_LLM_TIMEOUT" else 1

                    def generate_cloud(**kwargs):
                        self.assertEqual(local.call_count, local_attempts)
                        return gemini_response(content)

                    cloud.side_effect = generate_cloud
                    with self.assertLogs("app.outfits.application.policies", level="WARNING"):
                        result = (
                            LlmOutfitPersonalizer(_personal_recommender).personalize(base, OutfitPreferences())
                            if personal else get_outfit_service().get_today(37, 127)
                        )
                    self.assertEqual(local.call_count, local_attempts)
                    self.assertEqual([call.kwargs["timeout"] for call in local.call_args_list], [20] * local_attempts)
                    cloud.assert_called_once()
                    self.assertEqual(result.engine.provider, "gemini")
                    self.assertTrue(result.engine.fallback_used)
                    self.assertEqual(result.engine.fallback_reason, reason)
                    store = feedback_store_for_path(path)
                    generation = store.generation(result.engine.generation_id)
                    self.assertEqual(generation["provider"], "gemini")
                    self.assertEqual(generation["raw_response"], content)
                    self.assertEqual(len(store.generations()), local_attempts + 1)
                    feedback = store.create(
                        str(uuid4()), result.engine.generation_id, days[0].date.isoformat(), ["other"],
                    )
                    self.assertEqual(feedback["generation_id"], result.engine.generation_id)

    def test_exhausted_local_repair_calls_cloud_once_and_retains_all_attempts(self):
        """공통·개인화 모두 로컬 수정을 한 번으로 제한하고 클라우드의 최종 기록을 반환한다."""
        days = self.forecast.days[:1]
        content = outfit_fixtures.generated_content([days[0].date.isoformat()])
        base = self.fixture.recommender.recommend(days)
        for personal in (False, True):
            path = self.database_path.with_name(f"exhausted-{personal}.db")
            settings = Settings(
                "test", path, llm_model="local-model", cloud_fallback_enabled=True,
                gemini_api_key="test-key", gemini_model="cloud-model",
            )
            with (
                self.subTest(personal=personal),
                patch("app.outfits.bootstrap.get_settings", return_value=settings),
                patch("app.outfits.bootstrap.get_weather_service", return_value=self.fixture.weather_service),
                patch("app.outfits.infrastructure.clients.urlopen", side_effect=lambda *a, **kw: http_response(chat_envelope("{}"))) as local,
                patch("app.outfits.infrastructure.clients.genai.Client") as sdk,
            ):
                cloud = sdk.return_value.__enter__.return_value.models.generate_content
                cloud.return_value = gemini_response(content)
                with self.assertLogs("app.outfits.application.policies", level="WARNING"):
                    result = (
                        LlmOutfitPersonalizer(_personal_recommender).personalize(base, OutfitPreferences())
                        if personal else get_outfit_service().get_today(37, 127)
                    )
                self.assertEqual(local.call_count, 2)
                cloud.assert_called_once()
                self.assertEqual(result.engine.fallback_reason, "OUTFIT_LLM_INVALID_RESPONSE")
                store = feedback_store_for_path(path)
                self.assertEqual(len(store.generations()), 3)
                self.assertEqual(store.generation(result.engine.generation_id)["provider"], "gemini")


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
