"""업무 예외, 요청 검증 오류와 프레임워크 오류를 공통 JSON 응답으로 변환한다."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.common.errors.codes import ERROR_SPECS, ErrorCode
from app.common.errors.exceptions import AppError
from app.common.errors.schemas import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def _error_response(
    code: ErrorCode,
    *,
    message: str | None = None,
    details: list[ErrorDetail] | None = None,
    status_code: int | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """공통 오류 JSON 응답 생성"""
    spec = ERROR_SPECS[code]
    payload = ErrorResponse(
        code=code, message=message if message is not None else spec.message, details=details or [],
    )
    return JSONResponse(status_code=status_code or spec.status_code, content=payload.model_dump(mode="json"), headers=headers)


def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """업무 예외를 오류 응답으로 변환"""
    return _error_response(exc.error_code, message=exc.message)


def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """입력 검증 오류를 422 응답으로 변환"""
    details = [ErrorDetail(
        field=".".join(str(part) for part in error.get("loc", ())),
        message=error.get("msg", "입력값이 올바르지 않습니다."),
        type=error.get("type", "validation_error"),
    ) for error in exc.errors()]
    return _error_response(ErrorCode.COMMON_INVALID_REQUEST, details=details)


def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """HTTP 예외의 상태와 헤더 유지"""
    code = {
        404: ErrorCode.COMMON_NOT_FOUND,
        405: ErrorCode.COMMON_METHOD_NOT_ALLOWED,
    }.get(exc.status_code, ErrorCode.COMMON_HTTP_ERROR)
    return _error_response(code, status_code=exc.status_code, headers=exc.headers)


def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """내부 오류 기록 후 500 응답 반환"""
    logger.error("Unhandled API error: %s %s", request.method, request.url.path, exc_info=(type(exc), exc, exc.__traceback__))
    return _error_response(ErrorCode.COMMON_INTERNAL_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    """공통 예외 핸들러 등록"""
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
