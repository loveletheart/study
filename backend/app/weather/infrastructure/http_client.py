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
    def __init__(self, timeout_seconds: float = 10) -> None:
        self._timeout_seconds = timeout_seconds

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
                raise WeatherRateLimitError("날씨 제공 서비스의 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.") from exc
            if exc.code >= 500:
                raise WeatherProviderUnavailableError("날씨 제공 서비스를 일시적으로 사용할 수 없습니다.") from exc
            raise WeatherProviderDataError("날씨 제공 서비스가 요청을 처리하지 못했습니다.") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise WeatherProviderTimeoutError("날씨 제공 서비스의 응답 시간이 초과되었습니다.") from exc
        except URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise WeatherProviderTimeoutError("날씨 제공 서비스의 응답 시간이 초과되었습니다.") from exc
            raise WeatherProviderUnavailableError("날씨 제공 서비스에 연결할 수 없습니다.") from exc
        except (OSError, HTTPException) as exc:
            raise WeatherProviderUnavailableError("날씨 제공 서비스에 연결할 수 없습니다.") from exc

        if len(body) > 1_048_576:
            raise WeatherProviderDataError("날씨 제공 서비스의 응답 크기가 너무 큽니다.")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise WeatherProviderDataError("날씨 제공 서비스의 응답 형식이 올바르지 않습니다.") from exc
        if not isinstance(payload, dict) or payload.get("error"):
            raise WeatherProviderDataError("날씨 제공 서비스의 응답이 올바르지 않습니다.")
        return payload
