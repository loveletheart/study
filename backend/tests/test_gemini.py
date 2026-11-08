"""공식 SDK 경계에서 Gemini 요청, 응답 검증과 자동 전환 오류를 확인한다."""

# 표준 라이브러리
import json
import unittest
from datetime import timedelta
from unittest.mock import Mock, patch

# 외부 라이브러리
import httpx
from fastapi import Request
from google.genai import Client as SDKClient, errors, types

# 프로젝트 모듈
from app.common.errors.handlers import handle_app_error
from app.outfits.application.exceptions import (
    OutfitCloudAuthError,
    OutfitCloudNotConfiguredError,
    OutfitCloudRateLimitError,
    OutfitCloudResponseError,
    OutfitCloudTimeoutError,
    OutfitCloudUnavailableError,
)
from app.outfits.infrastructure.clients import MAX_RESPONSE_BYTES, GeminiClient
from app.outfits.infrastructure.recommenders import GeminiOutfitRecommender
from tests.test_outfits import generated_content, weather


def gemini_response(text: str = '{"days": []}', **changes) -> types.GenerateContentResponse:
    """내부 추론과 최종 답변을 포함한 실제 SDK 응답 객체를 구성한다."""
    return types.GenerateContentResponse.model_validate({
        "candidates": [{
            "finishReason": "STOP",
            "content": {"role": "model", "parts": [
                {"thought": True, "text": "내부 추론"}, {"text": text},
            ]},
        }],
        **changes,
    })


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        """네트워크 호출 대신 공식 SDK 클라이언트의 생성 경계를 대체한다."""
        factory = patch("app.outfits.infrastructure.clients.genai.Client")
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        self.sdk = self.factory.return_value.__enter__.return_value
        self.generate = self.sdk.models.generate_content
        self.generate.return_value = gemini_response("추천 결과")
        self.client = GeminiClient("test-key", 60, 8192)

    def test_sdk_receives_messages_schema_timeout_and_single_attempt(self):
        """SDK 메시지와 스키마, 밀리초 제한, 재시도 및 자동 후속 요청 비활성화를 확인한다."""
        messages = [
            {"role": "system", "content": "지침"}, {"role": "user", "content": "날씨"},
            {"role": "assistant", "content": "이전 답변"}, {"role": "user", "content": "요청"},
        ]
        schema = {"type": "object", "additionalProperties": False}
        self.assertEqual(self.client.chat("gemini-flash-latest", messages, schema), "추천 결과")
        self.assertEqual(self.factory.call_args.kwargs["api_key"], "test-key")
        options = self.factory.call_args.kwargs["http_options"]
        self.assertEqual(options.timeout, 60000)
        self.assertEqual(options.retry_options.attempts, 1)
        self.assertFalse(options.client_args["follow_redirects"])
        self.assertEqual(options.api_version, "v1beta")
        args = self.generate.call_args.kwargs
        self.assertEqual(args["model"], "gemini-flash-latest")
        self.assertEqual([content.role for content in args["contents"]], ["user", "model", "user"])
        self.assertEqual(args["contents"][0].parts[0].text, "날씨")
        config = args["config"]
        self.assertEqual(config.system_instruction, "지침")
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.response_json_schema, schema)
        self.assertEqual(config.max_output_tokens, 8192)
        self.assertFalse(config.automatic_continuation)
        self.assertTrue(config.automatic_function_calling.disable)
        self.generate.assert_called_once()
        self.factory.return_value.__exit__.assert_called_once()

    def test_sdk_service_errors_are_public_codes_without_private_details(self):
        """SDK의 인증, 할당량, 서비스 및 원격 시간 초과 오류를 공통 코드로 변환한다."""
        for code, expected, status in [
            (400, OutfitCloudUnavailableError, 503), (401, OutfitCloudAuthError, 503),
            (403, OutfitCloudAuthError, 503), (429, OutfitCloudRateLimitError, 503),
            (404, OutfitCloudUnavailableError, 503), (503, OutfitCloudUnavailableError, 503),
            (408, OutfitCloudTimeoutError, 504), (504, OutfitCloudTimeoutError, 504),
        ]:
            with self.subTest(code=code):
                self.generate.reset_mock()
                self.generate.side_effect = errors.APIError(code, {"error": {"message": "private test-key"}})
                with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING") as logs:
                    with self.assertRaises(expected) as caught:
                        self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                self.assertEqual(response.status_code, status)
                self.assertNotIn("private", response.body.decode())
                self.assertNotIn("test-key", response.body.decode())
                self.assertNotIn("test-key", " ".join(logs.output))
                self.generate.assert_called_once()

    def test_transport_timeouts_and_connection_errors_are_distinct(self):
        """연결 및 읽기 시간 초과를 일반 통신 실패와 구분하고 키 없이 기록한다."""
        for error, expected in [
            (httpx.ConnectTimeout("private test-key"), OutfitCloudTimeoutError),
            (httpx.ReadTimeout("private test-key"), OutfitCloudTimeoutError),
            (TimeoutError("private test-key"), OutfitCloudTimeoutError),
            (httpx.ConnectError("private test-key"), OutfitCloudUnavailableError),
            (OSError("private test-key"), OutfitCloudUnavailableError),
        ]:
            with self.subTest(error=type(error)):
                self.generate.side_effect = error
                with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING") as logs:
                    with self.assertRaises(expected):
                        self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
                self.assertNotIn("test-key", " ".join(logs.output))

    def test_invalid_key_details_are_authentication_errors(self):
        """HTTP 400으로 반환되는 잘못되거나 만료된 키도 인증 오류로 처리한다."""
        for reason in ["API_KEY_INVALID", "API_KEY_EXPIRED"]:
            with self.subTest(reason=reason):
                self.generate.side_effect = errors.APIError(400, {"error": {"details": [{"reason": reason}]}})
                with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING"):
                    with self.assertRaises(OutfitCloudAuthError):
                        self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})

    def test_unavailable_response_distinguishes_upstream_status_and_connection_failure(self):
        """공통 503 응답에서도 원격 HTTP 상태와 로컬 연결 실패를 구분하고 민감 정보는 숨긴다."""
        cases = [
            (errors.APIError(status, {"error": {"message": "private test-key"}}), f"HTTP {status}")
            for status in (400, 404, 500, 502, 503)
        ] + [
            (httpx.ConnectError("private test-key"), "HTTPS 연결"),
            (httpx.ProxyError("private test-key"), "프록시 연결"),
            (httpx.ReadError("private test-key"), "응답을 수신"),
            (httpx.WriteError("private test-key"), "데이터를 전송"),
            (OSError("private test-key"), "OSError"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected):
                self.generate.side_effect = error
                with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING"):
                    with self.assertRaises(OutfitCloudUnavailableError) as caught:
                        self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                payload = json.loads(response.body)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(payload["code"], "OUTFIT_CLOUD_UNAVAILABLE")
                self.assertIn(expected, payload["message"])
                self.assertNotIn("private", response.body.decode())
                self.assertNotIn("test-key", response.body.decode())

    def test_timeout_response_identifies_stage_without_exposing_exception_text(self):
        """공개 오류 응답에 시간 초과 단계와 제한만 포함하고 예외 원문은 숨긴다."""
        for error, stage in [
            (httpx.ConnectTimeout("private test-key"), "HTTPS 연결"),
            (httpx.ReadTimeout("private test-key"), "서버 응답"),
            (httpx.WriteTimeout("private test-key"), "요청 데이터"),
            (httpx.PoolTimeout("private test-key"), "HTTP 연결"),
        ]:
            with self.subTest(stage=stage):
                self.generate.side_effect = error
                with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING"):
                    with self.assertRaises(OutfitCloudTimeoutError) as caught:
                        self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
                response = handle_app_error(Request({"type": "http"}), caught.exception)
                payload = json.loads(response.body)
                self.assertEqual(response.status_code, 504)
                self.assertEqual(payload["code"], "OUTFIT_CLOUD_TIMEOUT")
                self.assertIn(stage, payload["message"])
                self.assertIn("60초", payload["message"])
                self.assertNotIn("test-key", payload["message"])
                self.assertNotIn("private", payload["message"])

    def test_server_deadline_is_distinct_from_client_timeout(self):
        """Google 서버가 반환한 처리 시간 초과에는 HTTP 상태를 표시한다."""
        self.generate.side_effect = errors.APIError(504, {"error": {"status": "DEADLINE_EXCEEDED"}})
        with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING"):
            with self.assertRaises(OutfitCloudTimeoutError) as caught:
                self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
        self.assertIn("HTTP 504", caught.exception.message)

    def test_sdk_parse_errors_use_cloud_response_error(self):
        """SDK 응답 파싱 실패를 클라우드 응답 오류로 변환한다."""
        self.generate.side_effect = ValueError("invalid response")
        with self.assertRaises(OutfitCloudResponseError):
            self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
        self.factory.return_value.__exit__.assert_called_once()

    def test_blocked_truncated_empty_and_nontext_responses_are_rejected(self):
        """차단, 출력 중단, 추론 전용 답변과 비텍스트 출력을 거부한다."""
        candidates = gemini_response().candidates
        responses = [
            gemini_response(""), gemini_response("  "), gemini_response("x" * (MAX_RESPONSE_BYTES + 1)),
            gemini_response(candidates=[]), gemini_response(candidates=candidates * 2),
            gemini_response(promptFeedback={"blockReason": "SAFETY"}),
        ]
        for finish in ["MAX_TOKENS", "SAFETY", "CONTINUATION"]:
            responses.append(gemini_response(candidates=[{"finishReason": finish}]))
        for parts in [[], [{"thought": True, "text": "내부 추론"}], [{"functionCall": {"name": "unexpected"}}]]:
            responses.append(gemini_response(candidates=[{
                "finishReason": "STOP", "content": {"role": "model", "parts": parts},
            }]))
        responses.append(gemini_response(candidates=[{
            "finishReason": "STOP", "content": {"role": "user", "parts": [{"text": "잘못된 역할"}]},
        }]))
        for index, response in enumerate(responses):
            with self.subTest(index=index):
                self.generate.return_value = response
                with self.assertRaises(OutfitCloudResponseError):
                    self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})

    def test_invalid_configuration_never_constructs_sdk(self):
        """빈 키와 잘못된 모델명은 인증 정보를 전송하기 전에 거부한다."""
        with self.assertRaises(OutfitCloudNotConfiguredError):
            GeminiClient("  ", 60, 8192)
        for model in ["", "../other", "gemini?key=secret", "https://other.example/model"]:
            with self.subTest(model=model), self.assertRaises(OutfitCloudNotConfiguredError):
                self.client.chat(model, [{"role": "user", "content": "날씨"}], {})
        self.factory.assert_not_called()

    def test_resource_model_name_is_normalized(self):
        """모델 리소스 접두사를 제거하고 시스템 지시문 없는 요청을 지원한다."""
        self.client.chat("models/gemini-flash-latest", [{"role": "user", "content": "날씨"}], {})
        args = self.generate.call_args.kwargs
        self.assertEqual(args["model"], "gemini-flash-latest")
        self.assertIsNone(args["config"].system_instruction)

    def test_real_sdk_transport_sends_schema_and_does_not_retry_503(self):
        """실제 SDK와 모의 HTTP 전송을 연결해 요청 변환과 503 재시도 억제를 검증한다."""
        requests = []

        def handle(request):
            """실제 SDK가 전송한 요청을 기록하고 서비스 오류를 반환한다."""
            requests.append(request)
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE", "message": "High demand"}})

        def create_sdk(*, api_key, http_options):
            """공식 SDK의 전송 계층만 모의 HTTP로 대체한다."""
            http_options.httpx_client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
            return SDKClient(api_key=api_key, http_options=http_options)

        self.factory.side_effect = create_sdk
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        with self.assertLogs("app.outfits.infrastructure.clients", level="WARNING"):
            with self.assertRaises(OutfitCloudUnavailableError):
                self.client.chat("gemini-flash-latest", [{"role": "user", "content": "날씨"}], schema)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers["x-goog-api-key"], "test-key")
        self.assertNotIn("test-key", str(requests[0].url))
        body = json.loads(requests[0].content)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["responseJsonSchema"], schema)


class GeminiRecommenderTests(unittest.TestCase):
    def test_valid_cloud_result_keeps_weather_and_provider_metadata(self):
        """주간 추천에서 원본 날씨와 Gemini 제공사 정보를 보존한다."""
        days = tuple(weather(date=weather().date + timedelta(days=i)) for i in range(7))
        client = Mock(spec=GeminiClient)
        client.chat.return_value = generated_content([day.date.isoformat() for day in days])
        result = GeminiOutfitRecommender(client, "gemini-flash-latest").recommend(days)
        self.assertEqual(result.engine.provider, "gemini")
        self.assertEqual(result.engine.model, "gemini-flash-latest")
        self.assertEqual(tuple(item.weather for item in result.recommendations), days)
        self.assertFalse(result.engine.fallback_used)
        client.chat.assert_called_once()

    def test_invalid_json_dates_and_identical_looks_use_cloud_error_code(self):
        """잘못된 JSON, 날짜와 동일한 추천을 클라우드 응답 오류로 처리한다."""
        day = weather()
        client = Mock(spec=GeminiClient)
        recommender = GeminiOutfitRecommender(client, "gemini-flash-latest")
        identical = json.loads(generated_content([day.date.isoformat()]))
        identical["days"][0]["worst"] = identical["days"][0]["best"]
        for value in ["not json", '{"days": []}', generated_content(["2000-01-01"]), json.dumps(identical)]:
            with self.subTest(value=value):
                client.chat.return_value = value
                with self.assertRaises(OutfitCloudResponseError):
                    recommender.recommend((day,))
        with self.assertRaises(OutfitCloudNotConfiguredError):
            GeminiOutfitRecommender(client, " ")
