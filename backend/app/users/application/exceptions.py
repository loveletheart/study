# 프로젝트 모듈
from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class UserNotFoundError(AppError):
    """요청한 사용자가 존재하지 않는다."""

    error_code = ErrorCode.USER_NOT_FOUND


class AuthenticationRequiredError(AppError):
    error_code = ErrorCode.AUTH_REQUIRED


class InvalidCredentialsError(AppError):
    error_code = ErrorCode.AUTH_INVALID_CREDENTIALS


class AuthorizationError(AppError):
    error_code = ErrorCode.AUTH_FORBIDDEN


class AuthenticationRateLimitError(AppError):
    error_code = ErrorCode.AUTH_RATE_LIMITED
