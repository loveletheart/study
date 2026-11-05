"""실제 API 호출 없이 OpenAI 요청·검증·공통 오류 확인."""

import io
import json
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from fastapi import Request

from app.common.errors.handlers import handle_app_error
from app.outfits.application.exceptions import (
    OutfitCloudAuthError, OutfitCloudNotConfiguredError, OutfitCloudRateLimitError,
    OutfitCloudResponseError, OutfitCloudTimeoutError, OutfitCloudUnavailableError,
)
from app.outfits.infrastructure.openai_client import MAX_RESPONSE_BYTES, OpenAIClient, _NoRedirect
from app.outfits.infrastructure.openai_recommender import OpenAIOutfitRecommender
from tests.test_ollama import http_response
from tests.test_outfits import generated_content, weather


def responses_envelope(text: str = '{"days": []}', **changes) -> bytes:
    """추론 항목과 최종 답변을 포함한 합성 응답 구성"""
    envelope = {
        "status": "completed", "error": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ],
    }
    return json.dumps({**envelope, **changes}, ensure_ascii=False).encode("utf-8")


class OpenAIClientTests(unittest.TestCase):
    def setUp(self):
        """인증 키와 네트워크를 대체한 클라이언트 준비"""
        opener = patch("app.outfits.infrastructure.openai_client.build_opener")
        self.open = opener.start().return_value.open
        self.addCleanup(opener.stop)
        self.client = OpenAIClient("test-key", 60, 8192)

    def test_request_uses_responses_api_schema_without_storing_response_state(self):
        """인증·스키마·토큰 제한과 추론 항목 뒤의 출력 처리 확인"""
        self.open.return_value = http_response(responses_envelope("생성 결과"))
        schema = {"type": "object", "additionalProperties": False}
        messages = [{"role": "system", "content": "지침"}, {"role": "user", "content": "날씨"}]
        self.assertEqual(self.client.chat("test-api-model", messages, schema), "생성 결과")
        request = self.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(payload["input"], messages)
        self.assertEqual(payload["model"], "test-api-model")
        self.assertFalse(payload["store"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["max_output_tokens"], 8192)
        self.assertEqual(payload["text"]["format"]["schema"], schema)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertNotIn("temperature", payload)
        self.assertEqual(self.open.call_args.kwargs["timeout"], 60)
        self.open.return_value.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_transport_errors_are_public_codes_without_private_details(self):
        """인증·한도·시간 초과·연결 실패를 공통 오류로 반환"""
        cases = [
            (401, OutfitCloudAuthError, 503), (403, OutfitCloudAuthError, 503),
            (429, OutfitCloudRateLimitError, 503), (400, OutfitCloudUnavailableError, 503),
            (404, OutfitCloudUnavailableError, 503), (500, OutfitCloudUnavailableError, 503),
            (302, OutfitCloudUnavailableError, 503),
        ]
        errors = [
            (HTTPError("url", code, "private detail", {}, io.BytesIO(b"private detail")), expected, status)
            for code, expected, status in cases
        ] + [
            (TimeoutError(), OutfitCloudTimeoutError, 504),
            (URLError(TimeoutError()), OutfitCloudTimeoutError, 504),
            (URLError("private detail"), OutfitCloudUnavailableError, 503),
        ]
        for error, expected, status in errors:
            with self.subTest(error=type(error), code=getattr(error, "code", None)):
                self.open.reset_mock()
                self.open.side_effect = error
                with self.assertRaises(expected) as caught:
                    self.client.chat("model", [], {})
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                self.assertEqual(response.status_code, status)
                payload = json.loads(response.body)
                self.assertEqual(payload["code"], caught.exception.error_code.value)
                self.assertIsNone(payload["data"])
                self.assertNotIn("private", response.body.decode())
                self.assertNotIn("test-key", response.body.decode())
                self.open.assert_called_once()

    def test_refusal_incomplete_failed_and_oversized_responses_are_rejected(self):
        """거절·출력 중단·빈 답변·도구 호출·잘못된 본문 거부"""
        refusal = {"type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "refusal", "refusal": "cannot comply"}]}
        cases = [
            b"invalid", b"[]", b"\xff", b"x" * (MAX_RESPONSE_BYTES + 1),
            responses_envelope(""), responses_envelope(status="incomplete"),
            responses_envelope(status="failed"), responses_envelope(error={"message": "private"}),
            responses_envelope(output=[]), responses_envelope(output=[refusal]),
            responses_envelope(output=[{"type": "function_call"}]),
            responses_envelope(output=[{"type": "reasoning"}]),
        ]
        for body in cases:
            with self.subTest(body_length=len(body)):
                self.open.return_value = http_response(body)
                with self.assertRaises(OutfitCloudResponseError):
                    self.client.chat("model", [], {})

    def test_missing_key_and_redirects_do_not_send_authenticated_requests(self):
        """키 미설정과 다른 주소로의 인증 전달 방지"""
        with self.assertRaises(OutfitCloudNotConfiguredError):
            OpenAIClient("  ", 60, 8192)
        self.open.assert_not_called()
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.example"))


class OpenAIRecommenderTests(unittest.TestCase):
    def test_valid_cloud_result_keeps_weather_and_provider_metadata(self):
        """7일 추천을 한 번에 생성하고 원본 날씨와 제공사 보존"""
        days = tuple(weather(date=weather().date + timedelta(days=i)) for i in range(7))
        client = Mock(spec=OpenAIClient)
        client.chat.return_value = generated_content([day.date.isoformat() for day in days])
        result = OpenAIOutfitRecommender(client, "api-model").recommend(days)
        self.assertEqual(result.engine.provider, "openai")
        self.assertEqual(result.engine.model, "api-model")
        self.assertFalse(result.engine.fallback_used)
        self.assertEqual(tuple(item.weather for item in result.recommendations), days)
        client.chat.assert_called_once()
        prompt = json.loads(client.chat.call_args.args[1][1]["content"])
        self.assertEqual(len(prompt["weather_days"]), 7)
        self.assertNotIn("latitude", prompt)
        self.assertNotIn("longitude", prompt)

    def test_cloud_json_date_and_clothing_errors_use_cloud_error_code(self):
        """공통 검증 실패도 실제 제공사의 오류 코드로 반환"""
        day = weather()
        client = Mock(spec=OpenAIClient)
        recommender = OpenAIOutfitRecommender(client, "api-model")
        content = json.loads(generated_content([day.date.isoformat()]))
        identical = json.loads(json.dumps(content))
        identical["days"][0]["worst"] = identical["days"][0]["best"]
        for value in ["not json", '{"days": []}', generated_content(["2000-01-01"]), json.dumps(identical)]:
            with self.subTest(value=value):
                client.chat.return_value = value
                with self.assertRaises(OutfitCloudResponseError):
                    recommender.recommend((day,))
        with self.assertRaises(OutfitCloudNotConfiguredError):
            OpenAIOutfitRecommender(client, " ")
