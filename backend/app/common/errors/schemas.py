"""모든 API가 공유하는 오류 응답 계약."""

from pydantic import Field

from app.common.errors.codes import ErrorCode
from app.common.responses import ApiResponse, ErrorDetail


class ErrorResponse(ApiResponse[None]):
    """HTTP 상태와 별개로 code를 통해 업무 오류 종류를 구분한다."""

    code: ErrorCode = Field(description="common/errors/codes.py에서 관리하는 오류 식별자")
    message: str = Field(description="사용자에게 보여줄 오류 설명")
    data: None = Field(default=None, description="실패 응답의 데이터는 null")
