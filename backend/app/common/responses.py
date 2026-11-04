"""모든 API의 공통 응답 형식."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """입력 검증 오류의 위치와 원인."""

    field: str = Field(description="오류 위치. 예: query.latitude, body.email, path.user_id")
    message: str = Field(description="해당 필드의 검증 실패 설명")
    type: str = Field(description="검증 오류 종류. 예: missing, less_than_equal")


class ApiResponse(BaseModel, Generic[T]):
    """성공 데이터와 오류 정보를 같은 필드로 반환한다."""

    code: str = Field(default="SUCCESS", description="성공은 SUCCESS, 실패는 공통 오류 코드")
    message: str = Field(default="요청이 성공했습니다.", description="응답 안내 메시지")
    data: T = Field(description="성공 결과. 실패 시 null")
    details: list[ErrorDetail] = Field(default_factory=list, description="입력 검증 오류 목록. 없으면 빈 배열")
