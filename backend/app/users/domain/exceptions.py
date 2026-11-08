# 프로젝트 모듈
from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class InvalidUserError(AppError, ValueError):
    """사용자 정보가 업무 규칙을 만족하지 않는다."""

    error_code = ErrorCode.USER_INVALID_DATA


class DuplicateEmailError(AppError):
    """이미 등록된 이메일이다."""

    error_code = ErrorCode.USER_DUPLICATE_EMAIL
