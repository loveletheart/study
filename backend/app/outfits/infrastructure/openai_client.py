"""OpenAI Responses API의 구조화 출력 호출."""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.outfits.application.exceptions import (
    OutfitCloudAuthError, OutfitCloudNotConfiguredError, OutfitCloudRateLimitError,
    OutfitCloudResponseError, OutfitCloudTimeoutError, OutfitCloudUnavailableError,
)

MAX_RESPONSE_BYTES = 1_048_576
RESPONSES_URL = "https://api.openai.com/v1/responses"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """인증 헤더가 다른 주소로 전달되는 리다이렉트 차단"""
        return None


class OpenAIClient:
    def __init__(self, api_key: str, timeout_seconds: float, max_output_tokens: int) -> None:
        """API 인증과 응답 제한 설정"""
        if not api_key.strip():
            raise OutfitCloudNotConfiguredError()
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._opener = build_opener(_NoRedirect())

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict) -> str:
        """단일 요청으로 JSON 스키마에 맞는 생성 결과 조회"""
        payload = {
            "model": model, "input": messages, "stream": False, "store": False,
            "max_output_tokens": self._max_output_tokens,
            "text": {"format": {
                "type": "json_schema", "name": "outfit_recommendations", "strict": True, "schema": schema,
            }},
        }
        request = Request(
            RESPONSES_URL, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}, method="POST",
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            if exc.code in {401, 403}:
                raise OutfitCloudAuthError() from exc
            if exc.code == 429:
                raise OutfitCloudRateLimitError() from exc
            raise OutfitCloudUnavailableError() from exc
        except TimeoutError as exc:
            raise OutfitCloudTimeoutError() from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise OutfitCloudTimeoutError() from exc
            raise OutfitCloudUnavailableError() from exc
        except (OSError, HTTPException) as exc:
            raise OutfitCloudUnavailableError() from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise OutfitCloudResponseError()
        try:
            envelope = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise OutfitCloudResponseError() from exc
        return _output_text(envelope)


def _output_text(envelope: object) -> str:
    """완료된 응답에서 추론 항목을 제외한 출력 텍스트 추출"""
    if not isinstance(envelope, dict) or envelope.get("status") != "completed" or envelope.get("error"):
        raise OutfitCloudResponseError()
    output = envelope.get("output")
    if not isinstance(output, list):
        raise OutfitCloudResponseError()
    parts = []
    for item in output:
        if not isinstance(item, dict):
            raise OutfitCloudResponseError()
        if item.get("type") == "reasoning":
            continue
        if item.get("type") != "message" or item.get("role") != "assistant" or item.get("status") != "completed":
            raise OutfitCloudResponseError()
        content = item.get("content")
        if not isinstance(content, list):
            raise OutfitCloudResponseError()
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise OutfitCloudResponseError()
            parts.append(part["text"])
    text = "".join(parts)
    if not text.strip():
        raise OutfitCloudResponseError()
    return text
