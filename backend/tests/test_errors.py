"""공통 오류 응답과 Swagger에 표시되는 공개 API 계약을 검증한다."""

import json
import unittest

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.common.errors.codes import ERROR_SPECS, ErrorCode
from app.common.errors.exceptions import AppError
from app.common.errors.handlers import (
    handle_app_error, handle_http_error, handle_unexpected_error, handle_validation_error,
)
from app.users.application.exceptions import UserNotFoundError
from app.users.domain.exceptions import DuplicateEmailError, InvalidUserError
from app.weather.application.exceptions import (
    InvalidWeatherQueryError, WeatherProviderDataError, WeatherProviderTimeoutError,
    WeatherProviderUnavailableError, WeatherRateLimitError,
)
from main import app


def request() -> Request:
    """로그와 오류 처리에 사용할 최소 HTTP 요청을 만든다. 소켓은 열지 않는다."""
    return Request({
        "type": "http", "method": "GET", "scheme": "http", "path": "/test",
        "query_string": b"", "headers": [], "server": ("localhost", 8000),
    })


class ErrorContractTests(unittest.TestCase):
    def test_every_code_has_a_definition(self):
        """모든 오류 코드의 정의와 고유성을 확인한다."""
        self.assertEqual(set(ErrorCode), set(ERROR_SPECS))
        self.assertEqual(len(ErrorCode), len({code.value for code in ErrorCode}))

    def test_business_errors_have_stable_codes_statuses_and_default_messages(self):
        """업무 오류의 코드·상태·기본 메시지를 확인한다."""
        cases = [
            (InvalidUserError, ErrorCode.USER_INVALID_DATA, 422),
            (DuplicateEmailError, ErrorCode.USER_DUPLICATE_EMAIL, 409),
            (UserNotFoundError, ErrorCode.USER_NOT_FOUND, 404),
            (InvalidWeatherQueryError, ErrorCode.WEATHER_INVALID_QUERY, 422),
            (WeatherProviderDataError, ErrorCode.WEATHER_INVALID_RESPONSE, 502),
            (WeatherProviderTimeoutError, ErrorCode.WEATHER_TIMEOUT, 504),
            (WeatherProviderUnavailableError, ErrorCode.WEATHER_UNAVAILABLE, 503),
            (WeatherRateLimitError, ErrorCode.WEATHER_RATE_LIMITED, 503),
        ]
        for exception_type, code, status in cases:
            with self.subTest(code=code):
                response = handle_app_error(request(), exception_type())
                payload = json.loads(response.body)
                self.assertEqual(response.status_code, status)
                self.assertEqual(payload, {"code": code.value, "message": ERROR_SPECS[code].message, "data": None, "details": []})

    def test_public_business_message_can_explain_specific_validation_rule(self):
        """업무 검증 오류의 공개 메시지를 확인한다."""
        response = handle_app_error(request(), InvalidUserError("이름은 1~100자여야 합니다."))
        self.assertEqual(json.loads(response.body)["message"], "이름은 1~100자여야 합니다.")
        self.assertIsInstance(InvalidUserError(), ValueError)

    def test_validation_error_omits_input_body_and_non_serializable_context(self):
        """검증 오류에서 원본 입력과 내부 정보를 제외한다."""
        error = RequestValidationError([{
            "loc": ("body", "email"), "msg": "Field required", "type": "missing",
            "input": {"password": "super-secret"}, "ctx": {"error": ValueError("private context")},
        }])
        response = handle_validation_error(request(), error)
        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["code"], "COMMON_INVALID_REQUEST")
        self.assertEqual(payload["details"], [{"field": "body.email", "message": "Field required", "type": "missing"}])
        self.assertNotIn("super-secret", response.body.decode())
        self.assertNotIn("private context", response.body.decode())

    def test_http_not_found_and_method_errors_keep_protocol_headers(self):
        """404·405 오류 코드와 HTTP 헤더 보존을 확인한다."""
        response = handle_http_error(request(), HTTPException(404, detail="not exposed"))
        self.assertEqual(json.loads(response.body)["code"], "COMMON_NOT_FOUND")
        response = handle_http_error(request(), HTTPException(405, headers={"Allow": "GET"}))
        self.assertEqual(response.headers["allow"], "GET")
        self.assertEqual(json.loads(response.body)["code"], "COMMON_METHOD_NOT_ALLOWED")

    def test_other_http_errors_keep_original_status(self):
        """일반 HTTP 오류의 원래 상태와 헤더를 유지한다."""
        response = handle_http_error(request(), HTTPException(401, headers={"WWW-Authenticate": "Bearer"}))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(json.loads(response.body)["code"], "COMMON_HTTP_ERROR")

    def test_unexpected_errors_are_logged_without_exposing_internal_details(self):
        """내부 오류를 기록하고 응답에서는 숨긴다."""
        with self.assertLogs("app.common.errors.handlers", level="ERROR"):
            response = handle_unexpected_error(request(), RuntimeError("database password=private"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.body)["code"], "COMMON_INTERNAL_ERROR")
        self.assertNotIn("password", response.body.decode())

    def test_handlers_are_registered_for_all_routes(self):
        """공통 예외 핸들러의 등록을 확인한다."""
        self.assertIs(app.exception_handlers[AppError], handle_app_error)
        self.assertIs(app.exception_handlers[RequestValidationError], handle_validation_error)
        self.assertIs(app.exception_handlers[HTTPException], handle_http_error)
        self.assertIs(app.exception_handlers[Exception], handle_unexpected_error)


class SwaggerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """검증에 사용할 OpenAPI 문서를 준비한다."""
        cls.openapi = app.openapi()

    def test_all_public_operations_have_readable_summaries_and_descriptions(self):
        """모든 API의 설명·고유 식별자·오류 스키마를 확인한다."""
        operation_ids = []
        for path, methods in self.openapi["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                with self.subTest(path=path, method=method):
                    self.assertTrue(operation["summary"].strip())
                    self.assertTrue(operation["description"].strip())
                    operation_ids.append(operation["operationId"])
                    schema = operation["responses"]["500"]["content"]["application/json"]["schema"]
                    self.assertEqual(schema["$ref"], "#/components/schemas/ErrorResponse")
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_every_success_and_error_schema_uses_the_common_envelope(self):
        """성공·오류 응답의 공통 형식을 확인한다."""
        schemas = self.openapi["components"]["schemas"]
        for path, methods in self.openapi["paths"].items():
            for operation in methods.values():
                for status, response in operation["responses"].items():
                    with self.subTest(path=path, status=status):
                        schema = response["content"]["application/json"]["schema"]
                        definition = schemas[schema["$ref"].split("/")[-1]]
                        self.assertEqual(set(definition["properties"]), {"code", "message", "data", "details"})
                        for example in response["content"]["application/json"].get("examples", {}).values():
                            # FastAPI는 OpenAPI 예시에서 null 값을 생략한다.
                            self.assertEqual(set(example["value"]) - {"data"}, {"code", "message", "details"})
                            self.assertIsNone(example["value"].get("data"))

    def test_validation_schema_and_examples_match_common_response(self):
        """422 응답 스키마와 공통 오류 예시를 확인한다."""
        for path, method in [
            ("/api/v1/users", "post"), ("/api/v1/users/{user_id}", "get"),
            ("/api/v1/weather/locations", "get"), ("/api/v1/weather/today", "get"),
            ("/api/v1/weather/weekly", "get"),
        ]:
            with self.subTest(path=path):
                response = self.openapi["paths"][path][method]["responses"]["422"]["content"]["application/json"]
                self.assertEqual(response["schema"]["$ref"], "#/components/schemas/ErrorResponse")
                self.assertEqual(response["examples"]["COMMON_INVALID_REQUEST"]["value"]["code"], "COMMON_INVALID_REQUEST")

    def test_status_503_retains_both_unavailable_and_rate_limit_examples(self):
        """503 응답에 장애·한도 초과 예시가 모두 있는지 확인한다."""
        response = self.openapi["paths"]["/api/v1/weather/today"]["get"]["responses"]["503"]
        self.assertEqual(set(response["content"]["application/json"]["examples"]), {"WEATHER_UNAVAILABLE", "WEATHER_RATE_LIMITED"})

    def test_response_properties_explain_their_meanings(self):
        """응답 필드에 설명이 있는지 확인한다."""
        for name in ["TodayWeatherResponse", "DailyForecastResponse", "HourlyForecastResponse", "LocationResponse", "UserResponse", "ErrorResponse"]:
            for field, definition in self.openapi["components"]["schemas"][name]["properties"].items():
                with self.subTest(schema=name, field=field):
                    self.assertTrue(definition.get("description", "").strip())

    def test_swagger_overview_lists_central_error_codes(self):
        """Swagger 안내에 전체 오류 코드가 표시되는지 확인한다."""
        for code in ErrorCode:
            self.assertIn(code.value, self.openapi["info"]["description"])


if __name__ == "__main__":
    unittest.main()
