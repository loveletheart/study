"""모든 API의 공통 응답 형식."""


# 표준 라이브러리
from typing import Generic, TypeVar

# 외부 라이브러리
from pydantic import BaseModel, Field


# 응답 데이터 타입
T = TypeVar("T")
ResponseCode = TypeVar("ResponseCode", bound=str)


# 공통 응답 모델
class ErrorDetail(BaseModel):
    """입력 검증 오류의 위치와 원인."""

    field: str = Field(description="오류 위치. 예: query.latitude, body.email, path.user_id")
    message: str = Field(description="해당 필드의 검증 실패 설명")
    type: str = Field(description="검증 오류 종류. 예: missing, less_than_equal")


class ResponseEnvelope(BaseModel, Generic[T, ResponseCode]):
    """성공·오류 응답이 데이터와 코드 타입에 맞춰 공통 필드를 공유한다."""

    code: ResponseCode = Field(description="성공은 SUCCESS, 실패는 공통 오류 코드")
    message: str = Field(description="응답 안내 메시지")
    data: T = Field(description="성공 결과. 실패 시 null")
    details: list[ErrorDetail] = Field(default_factory=list, description="입력 검증 오류 목록. 없으면 빈 배열")


class ApiResponse(ResponseEnvelope[T, str], Generic[T]):
    """성공 응답의 기본 코드와 메시지를 제공한다."""

    code: str = Field(default="SUCCESS", description="성공은 SUCCESS, 실패는 공통 오류 코드")
    message: str = Field(default="요청이 성공했습니다.", description="응답 안내 메시지")
