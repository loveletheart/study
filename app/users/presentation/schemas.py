"""API 요청과 응답의 형식. 업무 규칙은 domain에서 검증한다."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, examples=["김민성"])
    email: str = Field(
        min_length=1, max_length=254, examples=["minseong@example.com"]
    )


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str
