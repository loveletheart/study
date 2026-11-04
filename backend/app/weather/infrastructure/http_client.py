"""타임아웃·응답 크기 제한이 있는 동기 JSON 클라이언트."""

import json
import socket
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.weather.application.exceptions import (
    WeatherProviderDataError,
    WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
    WeatherRateLimitError,
)


class JsonHttpClient:
    # 외부 API 제한 시간 설정
    def __init__(self, timeout_seconds: float = 10) -> None:
        self._timeout_seconds = timeout_seconds

    # JSON 조회 및 외부 통신 오류 처리
    def get(self, url: str, parameters: dict) -> dict:
        request = Request(
            f"{url}?{urlencode(parameters)}",
            headers={"Accept": "application/json", "User-Agent": "StudyWeather/1.0"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read(1_048_577)
        except HTTPError as exc:
            exc.close()
            if exc.code == 429:
                raise WeatherRateLimitError() from exc
            if exc.code >= 500:
                raise WeatherProviderUnavailableError() from exc
            raise WeatherProviderDataError() from exc
        except (TimeoutError, socket.timeout) as exc:
            raise WeatherProviderTimeoutError() from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise WeatherProviderTimeoutError() from exc
            raise WeatherProviderUnavailableError() from exc
        except (OSError, HTTPException) as exc:
            raise WeatherProviderUnavailableError() from exc

        if len(body) > 1_048_576:
            raise WeatherProviderDataError()
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise WeatherProviderDataError() from exc
        if not isinstance(payload, dict) or payload.get("error"):
            raise WeatherProviderDataError()
        return payload
