from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class OutfitForecastError(AppError):
    """추천에 필요한 날짜나 날씨 정보가 올바르지 않음."""

    error_code = ErrorCode.OUTFIT_INVALID_FORECAST


class OutfitLlmNotConfiguredError(AppError):
    """LLM 모델을 아직 지정하지 않음."""

    error_code = ErrorCode.OUTFIT_LLM_NOT_CONFIGURED


class OutfitLlmUnavailableError(AppError):
    """LLM 서버 연결 또는 추론 실패."""

    error_code = ErrorCode.OUTFIT_LLM_UNAVAILABLE


class OutfitLlmModelNotFoundError(AppError):
    """설정한 모델이 로컬 서버에 없음."""

    error_code = ErrorCode.OUTFIT_LLM_MODEL_NOT_FOUND


class OutfitLlmTimeoutError(AppError):
    """LLM 응답 시간 초과."""

    error_code = ErrorCode.OUTFIT_LLM_TIMEOUT


class OutfitLlmResponseError(AppError):
    """LLM 응답 형식이나 날짜가 요청과 다름."""

    error_code = ErrorCode.OUTFIT_LLM_INVALID_RESPONSE
