from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class OutfitForecastError(AppError):
    """추천에 필요한 날짜나 날씨 정보가 올바르지 않음."""

    error_code = ErrorCode.OUTFIT_INVALID_FORECAST
