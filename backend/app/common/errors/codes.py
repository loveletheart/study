"""오류 코드·기본 메시지·HTTP 상태의 단일 관리 지점. 웹 라이브러리에 의존하지 않는다."""

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ErrorCode(str, Enum):
    """클라이언트가 오류 종류를 구분하는 안정적인 식별자."""

    COMMON_INVALID_REQUEST = "COMMON_INVALID_REQUEST"
    COMMON_NOT_FOUND = "COMMON_NOT_FOUND"
    COMMON_METHOD_NOT_ALLOWED = "COMMON_METHOD_NOT_ALLOWED"
    COMMON_HTTP_ERROR = "COMMON_HTTP_ERROR"
    COMMON_INTERNAL_ERROR = "COMMON_INTERNAL_ERROR"
    USER_INVALID_DATA = "USER_INVALID_DATA"
    USER_DUPLICATE_EMAIL = "USER_DUPLICATE_EMAIL"
    USER_NOT_FOUND = "USER_NOT_FOUND"
    WEATHER_INVALID_QUERY = "WEATHER_INVALID_QUERY"
    WEATHER_UNAVAILABLE = "WEATHER_UNAVAILABLE"
    WEATHER_TIMEOUT = "WEATHER_TIMEOUT"
    WEATHER_INVALID_RESPONSE = "WEATHER_INVALID_RESPONSE"
    WEATHER_RATE_LIMITED = "WEATHER_RATE_LIMITED"
    OUTFIT_INVALID_FORECAST = "OUTFIT_INVALID_FORECAST"
    OUTFIT_LLM_NOT_CONFIGURED = "OUTFIT_LLM_NOT_CONFIGURED"
    OUTFIT_LLM_UNAVAILABLE = "OUTFIT_LLM_UNAVAILABLE"
    OUTFIT_LLM_MODEL_NOT_FOUND = "OUTFIT_LLM_MODEL_NOT_FOUND"
    OUTFIT_LLM_TIMEOUT = "OUTFIT_LLM_TIMEOUT"
    OUTFIT_LLM_INVALID_RESPONSE = "OUTFIT_LLM_INVALID_RESPONSE"


@dataclass(frozen=True)
class ErrorSpec:
    """오류 코드에 대응하는 기본 HTTP 상태와 사용자 안내 메시지."""

    status_code: int
    message: str


ERROR_SPECS: Mapping[ErrorCode, ErrorSpec] = MappingProxyType({
    # 400번대 오류는 클라이언트 문제이므로, 클라이언트에게 안내 메시지를 전달합니다.
    ErrorCode.COMMON_INVALID_REQUEST: ErrorSpec(422, "요청 입력값을 확인해 주세요."),
    ErrorCode.COMMON_NOT_FOUND: ErrorSpec(404, "요청한 API 경로를 찾을 수 없습니다."),
    ErrorCode.COMMON_METHOD_NOT_ALLOWED: ErrorSpec(405, "허용되지 않은 HTTP 요청 방식입니다."),
    ErrorCode.COMMON_HTTP_ERROR: ErrorSpec(400, "HTTP 요청을 처리할 수 없습니다."),
    ErrorCode.COMMON_INTERNAL_ERROR: ErrorSpec(500, "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
    ErrorCode.USER_INVALID_DATA: ErrorSpec(422, "사용자 정보가 올바르지 않습니다."),
    ErrorCode.USER_DUPLICATE_EMAIL: ErrorSpec(409, "이미 등록된 이메일입니다."),
    ErrorCode.USER_NOT_FOUND: ErrorSpec(404, "사용자를 찾을 수 없습니다."),
    ErrorCode.WEATHER_INVALID_QUERY: ErrorSpec(422, "날씨 조회 조건을 확인해 주세요."),
    
    # 500번대 오류는 서버 내부 문제이므로, 클라이언트에게는 503 또는 504로 안내하고, 실제 서버 로그에서 원인을 확인하도록 유도합니다.
    ErrorCode.WEATHER_UNAVAILABLE: ErrorSpec(503, "날씨 제공 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."),
    ErrorCode.WEATHER_TIMEOUT: ErrorSpec(504, "날씨 제공 서비스의 응답 시간이 초과되었습니다."),
    ErrorCode.WEATHER_INVALID_RESPONSE: ErrorSpec(502, "날씨 제공 서비스의 응답 형식 또는 데이터가 올바르지 않습니다."),
    ErrorCode.WEATHER_RATE_LIMITED: ErrorSpec(503, "날씨 제공 서비스의 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."),
    ErrorCode.OUTFIT_INVALID_FORECAST: ErrorSpec(502, "옷차림 추천에 필요한 날씨 정보가 올바르지 않습니다."),
    ErrorCode.OUTFIT_LLM_NOT_CONFIGURED: ErrorSpec(503, "STUDY_LLM_MODEL에 사용할 로컬 모델명을 설정해 주세요."),
    ErrorCode.OUTFIT_LLM_UNAVAILABLE: ErrorSpec(503, "로컬 LLM 서버에 연결하거나 추천을 생성할 수 없습니다."),
    ErrorCode.OUTFIT_LLM_MODEL_NOT_FOUND: ErrorSpec(503, "설정한 모델을 로컬 LLM 서버에서 찾을 수 없습니다."),
    ErrorCode.OUTFIT_LLM_TIMEOUT: ErrorSpec(504, "로컬 LLM의 추천 생성 시간이 초과되었습니다."),
    ErrorCode.OUTFIT_LLM_INVALID_RESPONSE: ErrorSpec(502, "로컬 LLM이 올바른 옷차림 응답을 생성하지 못했습니다."),
})
