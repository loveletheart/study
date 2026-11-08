"""API 요청과 응답의 형식. 업무 규칙은 domain에서 검증한다."""

# 표준 라이브러리
from uuid import UUID

# 외부 라이브러리
from pydantic import BaseModel, ConfigDict, Field


class CreateUserRequest(BaseModel):
    """사용자 등록 입력. 이름과 이메일만 허용하고 앞뒤 공백을 제거한다."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, description="사용자 이름(공백 제거 후 1~100자)", examples=["김민성"])
    email: str = Field(
        min_length=1, max_length=254, description="이메일. 기본 형식을 검증하고 소문자로 저장하며 중복을 허용하지 않습니다.", examples=["minseong@example.com"]
    )


class UserResponse(BaseModel):
    """사용자 등록·조회 시 공개하는 식별자와 기본 정보."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="서버가 생성한 사용자 UUID")
    name: str = Field(description="앞뒤 공백을 제거한 사용자 이름")
    email: str = Field(description="소문자로 정규화한 이메일")
