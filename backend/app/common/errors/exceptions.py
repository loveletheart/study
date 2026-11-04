"""도메인과 애플리케이션에서도 사용할 수 있는 프레임워크 독립 예외."""

from app.common.errors.codes import ERROR_SPECS, ErrorCode


class AppError(Exception):
    """하위 예외가 error_code를 지정하면 기본 메시지와 HTTP 변환을 공통으로 처리한다."""

    error_code = ErrorCode.COMMON_INTERNAL_ERROR

    def __init__(self, message: str | None = None) -> None:
        """오류 코드의 기본 메시지로 예외 생성"""
        self.message = message if message is not None else ERROR_SPECS[self.error_code].message
        super().__init__(self.message)
