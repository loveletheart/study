# 프로젝트 모듈
from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError


class UserNotFoundError(AppError):
    """요청한 사용자가 존재하지 않는다."""

    error_code = ErrorCode.USER_NOT_FOUND
