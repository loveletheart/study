"""Ollama의 로컬 채팅 API 호출."""

import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.outfits.application.exceptions import (
    OutfitLlmModelNotFoundError, OutfitLlmResponseError, OutfitLlmTimeoutError, OutfitLlmUnavailableError,
)

MAX_RESPONSE_BYTES = 1_048_576


class OllamaClient:
    def __init__(self, base_url: str, timeout_seconds: float, context_size: int) -> None:
        """로컬 서버 주소와 추론 제한 설정"""
        self._url = base_url.rstrip("/") + "/api/chat"
        self._timeout_seconds = timeout_seconds
        self._context_size = context_size

    def chat(self, model: str, messages: list[dict[str, str]], schema: dict) -> str:
        """JSON 스키마를 지정해 단일 비스트리밍 응답 조회"""
        payload = {
            "model": model, "messages": messages, "format": schema, "stream": False,
            "options": {"temperature": 0.3, "num_predict": 8192, "num_ctx": self._context_size},
        }
        request = Request(
            self._url, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                raise OutfitLlmModelNotFoundError() from exc
            raise OutfitLlmUnavailableError() from exc
        except TimeoutError as exc:
            raise OutfitLlmTimeoutError() from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise OutfitLlmTimeoutError() from exc
            raise OutfitLlmUnavailableError() from exc
        except (OSError, HTTPException) as exc:
            raise OutfitLlmUnavailableError() from exc
        if len(body) > MAX_RESPONSE_BYTES:
            raise OutfitLlmResponseError()
        try:
            envelope = json.loads(body)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise OutfitLlmResponseError() from exc
        if not isinstance(envelope, dict):
            raise OutfitLlmResponseError()
        if envelope.get("error"):
            raise OutfitLlmUnavailableError()
        message = envelope.get("message")
        if (
            envelope.get("done") is not True or envelope.get("done_reason") == "length"
            or not isinstance(message, dict) or message.get("role") != "assistant"
        ):
            raise OutfitLlmResponseError()
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OutfitLlmResponseError()
        return content
