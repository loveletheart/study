from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class FeedbackNotFoundError(AppError):
    error_code = ErrorCode.OUTFIT_FEEDBACK_NOT_FOUND


class FeedbackConflictError(AppError):
    error_code = ErrorCode.OUTFIT_FEEDBACK_CONFLICT


class FeedbackInvalidError(AppError):
    error_code = ErrorCode.OUTFIT_FEEDBACK_INVALID
