"""오류 코드·기본 메시지·HTTP 상태의 단일 관리 지점. 웹 라이브러리에 의존하지 않는다."""


# 표준 라이브러리

# 표준 라이브러리
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


# 오류 코드
# 오류 코드
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
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    AUTH_RATE_LIMITED = "AUTH_RATE_LIMITED"
    WEATHER_INVALID_QUERY = "WEATHER_INVALID_QUERY"
    WEATHER_REGION_NOT_CONFIGURED = "WEATHER_REGION_NOT_CONFIGURED"
    WEATHER_UNAVAILABLE = "WEATHER_UNAVAILABLE"
    WEATHER_TIMEOUT = "WEATHER_TIMEOUT"
    WEATHER_INVALID_RESPONSE = "WEATHER_INVALID_RESPONSE"
    WEATHER_RATE_LIMITED = "WEATHER_RATE_LIMITED"
    OUTFIT_INVALID_FORECAST = "OUTFIT_INVALID_FORECAST"
    OUTFIT_WEEKLY_NOT_READY = "OUTFIT_WEEKLY_NOT_READY"
    OUTFIT_LLM_NOT_CONFIGURED = "OUTFIT_LLM_NOT_CONFIGURED"
    OUTFIT_LLM_UNAVAILABLE = "OUTFIT_LLM_UNAVAILABLE"
    OUTFIT_LLM_MODEL_NOT_FOUND = "OUTFIT_LLM_MODEL_NOT_FOUND"
    OUTFIT_LLM_TIMEOUT = "OUTFIT_LLM_TIMEOUT"
    OUTFIT_LLM_INVALID_RESPONSE = "OUTFIT_LLM_INVALID_RESPONSE"
    OUTFIT_CLOUD_NOT_CONFIGURED = "OUTFIT_CLOUD_NOT_CONFIGURED"
    OUTFIT_CLOUD_UNAVAILABLE = "OUTFIT_CLOUD_UNAVAILABLE"
    OUTFIT_CLOUD_AUTH_ERROR = "OUTFIT_CLOUD_AUTH_ERROR"
    OUTFIT_CLOUD_RATE_LIMITED = "OUTFIT_CLOUD_RATE_LIMITED"
    OUTFIT_CLOUD_TIMEOUT = "OUTFIT_CLOUD_TIMEOUT"
    OUTFIT_CLOUD_INVALID_RESPONSE = "OUTFIT_CLOUD_INVALID_RESPONSE"
    OUTFIT_FEEDBACK_NOT_FOUND = "OUTFIT_FEEDBACK_NOT_FOUND"
    OUTFIT_FEEDBACK_CONFLICT = "OUTFIT_FEEDBACK_CONFLICT"
    OUTFIT_FEEDBACK_INVALID = "OUTFIT_FEEDBACK_INVALID"


# 오류 명세 모델
# 오류 명세 모델
@dataclass(frozen=True)
class ErrorSpec:
    """오류 코드에 대응하는 기본 HTTP 상태와 사용자 안내 메시지."""

    status_code: int
    message: str


# 오류별 HTTP 상태와 기본 메시지: 위의 코드·명세 타입 정의 후 생성
# 오류별 HTTP 상태와 기본 메시지: 위의 코드·명세 타입 정의 후 생성
ERROR_SPECS: Mapping[ErrorCode, ErrorSpec] = MappingProxyType({
    ErrorCode.OUTFIT_FEEDBACK_NOT_FOUND: ErrorSpec(404, "수정안을 찾을 수 없습니다."),
    ErrorCode.OUTFIT_FEEDBACK_CONFLICT: ErrorSpec(409, "다른 변경이 저장됐습니다. 최신 수정안을 다시 불러와 주세요."),
    ErrorCode.OUTFIT_FEEDBACK_INVALID: ErrorSpec(422, "수정 내용과 검수 상태를 확인해 주세요."),
    # 400번대 오류는 클라이언트 문제이므로, 클라이언트에게 안내 메시지를 전달합니다.
    ErrorCode.COMMON_INVALID_REQUEST: ErrorSpec(422, "요청 입력값을 확인해 주세요."),
    ErrorCode.COMMON_NOT_FOUND: ErrorSpec(404, "요청한 API 경로를 찾을 수 없습니다."),
    ErrorCode.COMMON_METHOD_NOT_ALLOWED: ErrorSpec(405, "허용되지 않은 HTTP 요청 방식입니다."),
    ErrorCode.COMMON_HTTP_ERROR: ErrorSpec(400, "HTTP 요청을 처리할 수 없습니다."),
    ErrorCode.COMMON_INTERNAL_ERROR: ErrorSpec(500, "서버 내부 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),
    ErrorCode.USER_INVALID_DATA: ErrorSpec(422, "사용자 정보가 올바르지 않습니다."),
    ErrorCode.USER_DUPLICATE_EMAIL: ErrorSpec(409, "이미 등록된 이메일입니다."),
    ErrorCode.USER_NOT_FOUND: ErrorSpec(404, "사용자를 찾을 수 없습니다."),
    ErrorCode.AUTH_REQUIRED: ErrorSpec(401, "로그인이 필요합니다. 다시 로그인해 주세요."),
    ErrorCode.AUTH_INVALID_CREDENTIALS: ErrorSpec(401, "이메일 또는 비밀번호를 확인해 주세요."),
    ErrorCode.AUTH_FORBIDDEN: ErrorSpec(403, "이 요청을 처리할 권한이 없습니다."),
    ErrorCode.AUTH_RATE_LIMITED: ErrorSpec(429, "로그인 시도가 많습니다. 15분 후 다시 시도해 주세요."),
    ErrorCode.WEATHER_INVALID_QUERY: ErrorSpec(422, "날씨 조회 조건을 확인해 주세요."),
    ErrorCode.WEATHER_REGION_NOT_CONFIGURED: ErrorSpec(503, "시군구 경계 조회를 위해 VWORLD_API_KEY를 로컬 설정에 입력해 주세요."),
    
    # 500번대 오류는 서버 내부 문제이므로, 클라이언트에게는 503 또는 504로 안내하고, 실제 서버 로그에서 원인을 확인하도록 유도합니다.
    ErrorCode.WEATHER_UNAVAILABLE: ErrorSpec(503, "날씨 제공 서비스에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."),
    ErrorCode.WEATHER_TIMEOUT: ErrorSpec(504, "날씨 제공 서비스의 응답 시간이 초과되었습니다."),
    ErrorCode.WEATHER_INVALID_RESPONSE: ErrorSpec(502, "날씨 제공 서비스의 응답 형식 또는 데이터가 올바르지 않습니다."),
    ErrorCode.WEATHER_RATE_LIMITED: ErrorSpec(503, "날씨 제공 서비스의 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."),
    ErrorCode.OUTFIT_INVALID_FORECAST: ErrorSpec(502, "옷차림 추천에 필요한 날씨 정보가 올바르지 않습니다."),
    ErrorCode.OUTFIT_WEEKLY_NOT_READY: ErrorSpec(503, "주간 추천이 아직 준비되지 않았습니다. 매일 새벽 배치가 완료된 뒤 다시 조회해 주세요."),
    ErrorCode.OUTFIT_LLM_NOT_CONFIGURED: ErrorSpec(503, "STUDY_LLM_MODEL에 사용할 로컬 모델명을 설정해 주세요."),
    ErrorCode.OUTFIT_LLM_UNAVAILABLE: ErrorSpec(503, "로컬 LLM 서버에 연결하거나 추천을 생성할 수 없습니다."),
    ErrorCode.OUTFIT_LLM_MODEL_NOT_FOUND: ErrorSpec(503, "설정한 모델을 로컬 LLM 서버에서 찾을 수 없습니다."),
    ErrorCode.OUTFIT_LLM_TIMEOUT: ErrorSpec(504, "로컬 LLM의 추천 생성 시간이 초과되었습니다."),
    ErrorCode.OUTFIT_LLM_INVALID_RESPONSE: ErrorSpec(502, "로컬 LLM이 올바른 옷차림 응답을 생성하지 못했습니다."),
    ErrorCode.OUTFIT_CLOUD_NOT_CONFIGURED: ErrorSpec(503, "Gemini API 키와 사용할 API 모델명을 설정해 주세요."),
    ErrorCode.OUTFIT_CLOUD_UNAVAILABLE: ErrorSpec(503, "클라우드 LLM 연결과 API 모델 설정을 확인해 주세요."),
    ErrorCode.OUTFIT_CLOUD_AUTH_ERROR: ErrorSpec(503, "Gemini API 키 또는 접근 권한을 확인해 주세요."),
    ErrorCode.OUTFIT_CLOUD_RATE_LIMITED: ErrorSpec(503, "Gemini API 요청 한도 또는 사용 가능 크레딧을 확인해 주세요."),
    ErrorCode.OUTFIT_CLOUD_TIMEOUT: ErrorSpec(504, "클라우드 LLM의 추천 생성 시간이 초과되었습니다."),
    ErrorCode.OUTFIT_CLOUD_INVALID_RESPONSE: ErrorSpec(502, "클라우드 LLM이 올바른 옷차림 응답을 생성하지 못했습니다."),
})
