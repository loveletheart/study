"""Google GenAI 공식 SDK로 구조화된 옷차림 응답을 요청한다."""

import logging
import math
import re
from time import perf_counter

import httpx
from google import genai
from google.genai import errors, types

from app.outfits.application.exceptions import (
    OutfitCloudAuthError, OutfitCloudNotConfiguredError, OutfitCloudRateLimitError,
    OutfitCloudResponseError, OutfitCloudTimeoutError, OutfitCloudUnavailableError,
)

MAX_RESPONSE_BYTES = 1_048_576
logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, api_key: str, timeout_seconds: float, max_output_tokens: int) -> None:
        """인증 키와 응답 대기 시간, 출력 토큰 상한을 설정한다."""
        if not api_key.strip():
            raise OutfitCloudNotConfiguredError()
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict) -> str:
        """공식 SDK에 메시지와 JSON 스키마를 전달하고 최종 텍스트를 검증한다."""
        model = model.strip().removeprefix("models/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model):
            raise OutfitCloudNotConfiguredError()
        instructions = []
        contents = []
        for message in messages:
            if message["role"] == "system":
                instructions.append(message["content"])
            elif message["role"] in {"user", "assistant"}:
                contents.append(types.Content(
                    role="model" if message["role"] == "assistant" else "user",
                    parts=[types.Part.from_text(text=message["content"])],
                ))
            else:
                raise OutfitCloudResponseError()
        if not contents:
            raise OutfitCloudResponseError()
        options = types.HttpOptions(
            api_version="v1beta", timeout=math.ceil(self._timeout_seconds * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
            client_args={"follow_redirects": False},
        )
        config = types.GenerateContentConfig(
            system_instruction="\n\n".join(instructions) or None,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json", response_json_schema=schema,
            automatic_continuation=False,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        started = perf_counter()
        try:
            with genai.Client(api_key=self._api_key, http_options=options) as client:
                response = client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as exc:
            _log_api_error(exc, model, self._api_key)
            if exc.code in {401, 403} or (exc.code == 400 and _invalid_api_key(exc.details)):
                raise OutfitCloudAuthError() from exc
            if exc.code == 429:
                raise OutfitCloudRateLimitError() from exc
            if exc.code in {408, 504}:
                raise OutfitCloudTimeoutError(
                    f"Gemini 서버가 요청 처리 시간 초과를 반환했습니다(HTTP {exc.code})."
                ) from exc
            raise OutfitCloudUnavailableError(_api_unavailable_message(exc.code)) from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning(
                "Gemini 요청 시간 초과: model=%s, elapsed_seconds=%.2f, timeout_seconds=%s, cause=%s",
                model, perf_counter() - started, self._timeout_seconds, type(exc).__name__,
            )
            raise OutfitCloudTimeoutError(_timeout_message(exc, self._timeout_seconds)) from exc
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("Gemini 연결 실패: model=%s, cause=%s", model, type(exc).__name__)
            raise OutfitCloudUnavailableError(_connection_error_message(exc)) from exc
        except ValueError as exc:
            raise OutfitCloudResponseError() from exc
        return _output_text(response)


def _api_unavailable_message(status: int) -> str:
    """우리 서버의 공통 503 응답과 Gemini가 반환한 원래 HTTP 상태를 구분한다."""
    reason = {
        400: "요청 형식이나 모델 설정을 거부했습니다",
        404: "요청한 모델 또는 API 경로를 찾지 못했습니다",
        500: "내부 오류를 반환했습니다",
        502: "게이트웨이 오류를 반환했습니다",
        503: "서비스를 일시적으로 제공할 수 없다고 응답했습니다",
    }.get(status, "요청을 처리하지 못했습니다")
    return f"Gemini 서버가 {reason}(HTTP {status})."


def _connection_error_message(error: Exception) -> str:
    """예외 원문을 숨기고 연결 실패 종류만 안내한다."""
    if isinstance(error, httpx.ProxyError):
        reason = "프록시 연결에 실패했습니다"
    elif isinstance(error, httpx.ConnectError):
        reason = "HTTPS 연결에 실패했습니다"
    elif isinstance(error, httpx.ReadError):
        reason = "서버 응답을 수신하는 중 통신에 실패했습니다"
    elif isinstance(error, httpx.WriteError):
        reason = "요청 데이터를 전송하는 중 통신에 실패했습니다"
    else:
        reason = "서버와 통신하는 중 오류가 발생했습니다"
    return f"Gemini {reason}({type(error).__name__})."


def _timeout_message(error: Exception, timeout_seconds: float) -> str:
    """민감한 예외 원문 대신 시간 초과 단계와 설정된 대기 제한을 안내한다."""
    if isinstance(error, httpx.ConnectTimeout):
        stage = "HTTPS 연결을 맺는 중"
    elif isinstance(error, httpx.ReadTimeout):
        stage = "서버 응답을 기다리거나 읽는 중"
    elif isinstance(error, httpx.WriteTimeout):
        stage = "요청 데이터를 전송하는 중"
    elif isinstance(error, httpx.PoolTimeout):
        stage = "사용 가능한 HTTP 연결을 확보하는 중"
    else:
        stage = "요청을 처리하는 중"
    return f"Gemini {stage} 시간 초과가 발생했습니다(대기 제한 {timeout_seconds:g}초)."


def _log_api_error(error: errors.APIError, model: str, api_key: str) -> None:
    """키를 가리고 길이를 제한한 SDK 오류 원인을 서버 로그에만 기록한다."""
    status = " ".join(str(error.status or "UNKNOWN").replace(api_key, "[REDACTED]").split())[:64]
    message = " ".join(str(error.message or "Google 오류 본문이 없습니다.").replace(api_key, "[REDACTED]").split())[:400]
    logger.warning(
        "Gemini API 오류: status=%s, api_status=%s, model=%s, message=%s",
        error.code, status, model, message,
    )


def _invalid_api_key(details: object) -> bool:
    """SDK 오류 세부 정보에서 잘못되거나 만료된 API 키를 구분한다."""
    if not isinstance(details, dict):
        return False
    error = details.get("error", details)
    items = error.get("details") if isinstance(error, dict) else None
    return isinstance(items, list) and any(
        isinstance(item, dict) and item.get("reason") in ("API_KEY_INVALID", "API_KEY_EXPIRED")
        for item in items
    )


def _output_text(response: types.GenerateContentResponse) -> str:
    """정상 완료된 단일 후보에서 내부 추론을 제외한 텍스트만 추출한다."""
    if response.prompt_feedback and response.prompt_feedback.block_reason:
        raise OutfitCloudResponseError()
    candidates = response.candidates
    if not candidates or len(candidates) != 1:
        raise OutfitCloudResponseError()
    candidate = candidates[0]
    if candidate.finish_reason != types.FinishReason.STOP:
        raise OutfitCloudResponseError()
    content = candidate.content
    if content is None or content.role != "model" or not content.parts:
        raise OutfitCloudResponseError()
    texts = []
    for part in content.parts:
        if part.thought is True:
            continue
        if not isinstance(part.text, str):
            raise OutfitCloudResponseError()
        texts.append(part.text)
    text = "".join(texts)
    if not text.strip() or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise OutfitCloudResponseError()
    return text
