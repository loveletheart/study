"""실제 모델 없이 로컬 LLM 요청·응답 검증과 오류 처리 확인."""

import io
import json
import os
import unittest
from dataclasses import replace
from datetime import timedelta
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from fastapi import Request

from app.common.config import Settings, get_settings
from app.common.errors.handlers import handle_app_error
from app.outfits.application.dto import GeneratedOutfits
from app.outfits.application.exceptions import (
    OutfitLlmModelNotFoundError, OutfitLlmNotConfiguredError, OutfitLlmResponseError,
    OutfitLlmTimeoutError, OutfitLlmUnavailableError,
)
from app.outfits.application.services import OutfitService
from app.outfits.bootstrap import get_outfit_service
from app.outfits.domain.models import TemperatureBasis
from app.outfits.domain.rules import build_weekly_wardrobe, temperature_reference
from app.outfits.infrastructure.ollama_client import MAX_RESPONSE_BYTES, OllamaClient
from app.outfits.infrastructure.ollama_recommender import OllamaOutfitRecommender
from tests import test_outfits as outfit_fixtures
from tests.test_outfits import generated_content, weather


def http_response(body: bytes) -> Mock:
    """통신 없이 읽을 수 있는 HTTP 응답 준비"""
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = body
    return response


def chat_envelope(content: str = '{"days": []}', **changes) -> bytes:
    """비스트리밍 Ollama 응답의 합성 데이터 생성"""
    payload = {"message": {"role": "assistant", "content": content}, "done": True, "done_reason": "stop"}
    return json.dumps({**payload, **changes}, ensure_ascii=False).encode("utf-8")


class OllamaClientTests(unittest.TestCase):
    @patch("app.outfits.infrastructure.ollama_client.urlopen")
    def test_chat_sends_the_model_schema_and_non_streaming_options(self, urlopen):
        """로컬 주소·모델·스키마·추론 옵션 전달 확인"""
        urlopen.return_value = http_response(chat_envelope("생성 결과"))
        schema = {"type": "object", "properties": {"days": {"type": "array"}}}
        result = OllamaClient("http://127.0.0.1:11434/", 180, 16384).chat(
            "my-local-model", [{"role": "user", "content": "날씨"}], schema,
        )
        self.assertEqual(result, "생성 결과")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(payload["model"], "my-local-model")
        self.assertEqual(payload["format"], schema)
        self.assertIs(payload["stream"], False)
        self.assertEqual(payload["options"]["num_ctx"], 16384)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 180)
        urlopen.return_value.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    @patch("app.outfits.infrastructure.ollama_client.urlopen")
    def test_connection_model_and_timeout_failures_have_public_error_codes(self, urlopen):
        """연결 실패·모델 없음·시간 초과를 공통 오류로 변환"""
        cases = [
            (TimeoutError(), OutfitLlmTimeoutError, 504),
            (URLError(TimeoutError()), OutfitLlmTimeoutError, 504),
            (URLError("connection refused"), OutfitLlmUnavailableError, 503),
            (IncompleteRead(b"partial"), OutfitLlmUnavailableError, 503),
            (HTTPError("url", 404, "missing", {}, io.BytesIO()), OutfitLlmModelNotFoundError, 503),
            (HTTPError("url", 429, "busy", {}, io.BytesIO()), OutfitLlmUnavailableError, 503),
            (HTTPError("url", 500, "error", {}, io.BytesIO()), OutfitLlmUnavailableError, 503),
        ]
        for error, expected, status in cases:
            with self.subTest(error=error):
                urlopen.side_effect = error
                with self.assertRaises(expected) as caught:
                    OllamaClient("http://localhost:11434", 1, 4096).chat("model", [], {})
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                self.assertEqual(response.status_code, status)
                self.assertIsNone(json.loads(response.body)["data"])

    @patch("app.outfits.infrastructure.ollama_client.urlopen")
    def test_invalid_incomplete_or_oversized_chat_responses_are_rejected(self, urlopen):
        """JSON 오류·빈 답변·생성 중단·응답 크기 초과 거부"""
        cases = [
            b"not JSON", b"[]", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1),
            chat_envelope(""), chat_envelope("   "), chat_envelope(done=False),
            chat_envelope(done_reason="length"), chat_envelope(message={"role": "user", "content": "wrong"}),
            chat_envelope(message=None),
        ]
        for body in cases:
            with self.subTest(length=len(body)):
                urlopen.return_value = http_response(body)
                with self.assertRaises(OutfitLlmResponseError):
                    OllamaClient("http://localhost:11434", 1, 4096).chat("model", [], {})

    @patch("app.outfits.infrastructure.ollama_client.urlopen")
    def test_server_error_body_is_not_exposed_to_the_caller(self, urlopen):
        """서버 오류의 내부 문자열을 공개 응답에서 제외"""
        urlopen.return_value = http_response(b'{"error":"private filesystem path"}')
        with self.assertRaises(OutfitLlmUnavailableError) as caught:
            OllamaClient("http://localhost:11434", 1, 4096).chat("model", [], {})
        response = handle_app_error(Request({"type": "http"}), caught.exception)
        self.assertNotIn("private", response.body.decode())


class OllamaRecommenderTests(unittest.TestCase):
    def setUp(self):
        """실제 HTTP 요청을 하지 않는 추론 클라이언트 준비"""
        self.client = Mock(spec=OllamaClient)
        self.day = weather()
        self.content = generated_content([self.day.date.isoformat()])
        self.client.chat.return_value = self.content
        self.recommender = OllamaOutfitRecommender(self.client, "local-model")

    def test_one_request_contains_all_seven_days_and_exact_output_schema(self):
        """주간 날씨를 한 번에 보내고 날짜·개수를 출력 스키마에 반영"""
        days = tuple(replace(self.day, date=self.day.date + timedelta(days=index)) for index in range(7))
        dates = [day.date.isoformat() for day in days]
        self.client.chat.return_value = generated_content(dates)
        generated = self.recommender.recommend(days)
        self.client.chat.assert_called_once()
        model, messages, schema = self.client.chat.call_args.args
        prompt = json.loads(messages[1]["content"])
        self.assertEqual(model, "local-model")
        self.assertEqual([day["date"] for day in prompt["weather_days"]], dates)
        self.assertEqual(schema["properties"]["days"]["minItems"], 7)
        self.assertEqual(schema["properties"]["days"]["maxItems"], 7)
        self.assertEqual(schema["$defs"]["GeneratedDay"]["properties"]["date"]["enum"], dates)
        self.assertEqual(len(generated.recommendations), 7)
        self.assertEqual(generated.engine.provider, "ollama")
        self.assertEqual(generated.engine.model, "local-model")

    def test_source_weather_and_temperature_basis_are_owned_by_the_server(self):
        """모델이 생성한 의류와 서버의 원본 날씨를 분리"""
        day = replace(self.day, apparent_temperature_min_c=2, apparent_temperature_max_c=9)
        result = self.recommender.recommend((day,)).recommendations[0]
        self.assertEqual(result.weather, day)
        self.assertEqual(result.temperature_basis, TemperatureBasis.APPARENT)
        self.assertEqual(result.reference_temperature_c, 9)
        self.assertEqual(result.best.top, "블루 셔츠")

    def test_missing_weather_information_is_preserved_and_explained(self):
        """원본 null 보존과 실제 기온 사용·누락 안내 확인"""
        day = replace(self.day, precipitation_probability_percent=None, wind_speed_m_s=None)
        result = self.recommender.recommend((day,)).recommendations[0]
        prompt = json.loads(self.client.chat.call_args.args[1][1]["content"])
        self.assertIsNone(prompt["weather_days"][0]["precipitation_probability_percent"])
        self.assertIsNone(result.weather.precipitation_probability_percent)
        self.assertEqual(result.temperature_basis, TemperatureBasis.ACTUAL)
        self.assertTrue(any("실제 기온" in reason for reason in result.reasons))
        self.assertTrue(any("강수확률 정보" in text for text in result.precautions))
        self.assertTrue(any("풍속 정보" in text for text in result.precautions))

    def test_malformed_or_incomplete_generated_content_is_rejected(self):
        """필수 필드·길이·타입·추가 필드가 잘못된 생성 결과 거부"""
        mutations = [
            lambda p: p["days"][0].pop("worst"),
            lambda p: p["days"][0].update(reasons=[]),
            lambda p: p["days"][0].update(avoid_reasons=["   "]),
            lambda p: p["days"][0]["best"].update(top=42),
            lambda p: p["days"][0]["best"].update(top="x" * 201),
            lambda p: p["days"][0].update(weather={"temperature_max_c": 99}),
            lambda p: p.update(extra="unexpected"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                payload = json.loads(self.content)
                mutate(payload)
                self.client.chat.return_value = json.dumps(payload)
                with self.assertRaises(OutfitLlmResponseError):
                    self.recommender.recommend((self.day,))

    def test_plain_text_and_markdown_code_blocks_are_rejected(self):
        """자유 형식 텍스트와 코드 블록을 정상 JSON으로 취급하지 않음"""
        for content in ["셔츠를 입으세요", f"```json\n{self.content}\n```"]:
            with self.subTest(content=content):
                self.client.chat.return_value = content
                with self.assertRaises(OutfitLlmResponseError):
                    self.recommender.recommend((self.day,))

    def test_wrong_duplicate_reordered_or_missing_dates_are_rejected(self):
        """모델 응답의 날짜 변경·중복·순서 변경·누락 거부"""
        days = tuple(replace(self.day, date=self.day.date + timedelta(days=index)) for index in range(7))
        dates = [day.date.isoformat() for day in days]
        for returned in [dates[:6], dates[::-1], [dates[0]] * 7, ["2020-01-01", *dates[1:]]]:
            with self.subTest(returned=returned):
                self.client.chat.return_value = generated_content(returned)
                with self.assertRaises(OutfitLlmResponseError):
                    self.recommender.recommend(days)

    def test_best_and_worst_must_have_different_clothes(self):
        """베스트와 워스트가 동일한 응답 거부"""
        payload = json.loads(self.content)
        payload["days"][0]["worst"] = payload["days"][0]["best"]
        self.client.chat.return_value = json.dumps(payload)
        with self.assertRaises(OutfitLlmResponseError):
            self.recommender.recommend((self.day,))

    def test_no_model_or_invalid_day_count_stops_before_inference(self):
        """모델 미설정·잘못된 요청 개수는 추론 전에 거부"""
        with self.assertRaises(OutfitLlmNotConfiguredError):
            OllamaOutfitRecommender(self.client, " ")
        for days in [(), (self.day,) * 8]:
            with self.assertRaises(OutfitLlmResponseError):
                self.recommender.recommend(days)
        self.client.chat.assert_not_called()

    def test_inference_failure_is_not_replaced_by_a_fixed_clothing_result(self):
        """추론 실패를 고정 의류 추천으로 대체하지 않음"""
        self.client.chat.side_effect = OutfitLlmTimeoutError()
        with self.assertRaises(OutfitLlmTimeoutError):
            self.recommender.recommend((self.day,))

    def test_service_rejects_an_adapter_that_changes_weather_or_temperature(self):
        """다른 추론 구현도 원본 날씨·온도·날짜를 변경할 수 없음"""
        fixture = outfit_fixtures.OutfitIntegrationTests()
        fixture.setUp()
        snapshot = fixture.reader.get_forecast(37, 127)
        generated = fixture.recommender.recommend(snapshot.days[:1])
        original = generated.recommendations[0]
        for modified in [
            replace(original, reference_temperature_c=999),
            replace(original, date=original.date + timedelta(days=1)),
            replace(original, weather=replace(original.weather, temperature_max_c=99)),
        ]:
            with self.subTest(modified=modified):
                recommender = Mock()
                recommender.recommend.return_value = GeneratedOutfits((modified,), generated.engine)
                with self.assertRaises(OutfitLlmResponseError):
                    OutfitService(fixture.reader, recommender).get_today(37, 127)

    def test_temperature_reference_and_weekly_deduplication_remain_deterministic(self):
        """온도 기준과 주간 준비물 집계는 서버에서 수행"""
        for low, high in [(None, None), (None, 4), (4, None)]:
            day = replace(self.day, apparent_temperature_min_c=low, apparent_temperature_max_c=high)
            self.assertEqual(temperature_reference(day), (TemperatureBasis.ACTUAL, 20))
        self.client.chat.return_value = generated_content([self.day.date.isoformat()], outerwear=None)
        recommendation = self.recommender.recommend((self.day,)).recommendations[0]
        wardrobe = build_weekly_wardrobe((recommendation,) * 7)
        self.assertEqual(wardrobe.tops, ("블루 셔츠",))
        self.assertEqual(wardrobe.outerwear, ())
        self.assertEqual(wardrobe.accessories, ("우산",))

    def test_invalid_weather_values_still_fail_before_inference(self):
        """LLM 전환 후에도 비정상 기온·확률·풍속 입력 거부"""
        for changes in [
            {"temperature_min_c": float("nan")}, {"temperature_max_c": float("inf")},
            {"temperature_min_c": 30}, {"precipitation_probability_percent": 101},
            {"wind_speed_m_s": -1}, {"uv_index": -1},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                weather(**changes)


class LlmSettingsTests(unittest.TestCase):
    def setUp(self):
        """실제 환경을 변경하지 않는 설정 검증 준비"""
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        dotenv = patch("app.common.config.dotenv_values", return_value={})
        self.dotenv = dotenv.start()
        self.addCleanup(dotenv.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_default_settings_do_not_select_or_download_a_model(self):
        """초기 설정에서 모델을 선택하거나 다운로드하지 않음"""
        settings = get_settings()
        self.assertEqual(settings.llm_base_url, "http://127.0.0.1:11434")
        self.assertEqual(settings.llm_model, "")
        self.assertEqual(settings.llm_timeout_seconds, 180)
        self.assertEqual(settings.llm_context_size, 16384)

    def test_environment_overrides_dotenv_and_keeps_the_exact_model_name(self):
        """환경변수를 우선해 모델명과 접속 주소 지정"""
        self.dotenv.return_value = {"STUDY_LLM_MODEL": "dotenv-model"}
        with patch.dict(os.environ, {
            "STUDY_LLM_MODEL": " custom-model:tag ", "STUDY_LLM_BASE_URL": "http://localhost:11434/",
            "STUDY_LLM_TIMEOUT_SECONDS": "300", "STUDY_LLM_CONTEXT_SIZE": "8192",
        }):
            settings = get_settings()
        self.assertEqual(settings.llm_model, "custom-model:tag")
        self.assertEqual(settings.llm_base_url, "http://localhost:11434")
        self.assertEqual(settings.llm_timeout_seconds, 300)
        self.assertEqual(settings.llm_context_size, 8192)

    def test_invalid_endpoint_timeout_and_context_settings_are_rejected(self):
        """접속 주소·제한 시간·문맥 길이의 잘못된 값 거부"""
        cases = [
            ("STUDY_LLM_BASE_URL", "file:///tmp/model"), ("STUDY_LLM_BASE_URL", "http://user:password@localhost"),
            ("STUDY_LLM_BASE_URL", "http://localhost:99999"), ("STUDY_LLM_BASE_URL", "http://localhost?secret=value"),
            ("STUDY_LLM_TIMEOUT_SECONDS", "nan"), ("STUDY_LLM_TIMEOUT_SECONDS", "0"),
            ("STUDY_LLM_CONTEXT_SIZE", "2048.5"), ("STUDY_LLM_CONTEXT_SIZE", "1024"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}):
                get_settings.cache_clear()
                with self.assertRaises(ValueError):
                    get_settings()

    @patch("app.outfits.bootstrap.get_weather_service")
    @patch("app.outfits.bootstrap.get_settings")
    def test_unconfigured_model_returns_503_before_weather_is_requested(self, settings, weather_service):
        """모델 미설정 시 날씨 조회 전에 공통 503 반환"""
        settings.return_value = Settings("test", Path("unused.db"))
        with self.assertRaises(OutfitLlmNotConfiguredError) as caught:
            get_outfit_service()
        weather_service.assert_not_called()
        response = handle_app_error(Request({"type": "http"}), caught.exception)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["code"], "OUTFIT_LLM_NOT_CONFIGURED")


if __name__ == "__main__":
    unittest.main()
