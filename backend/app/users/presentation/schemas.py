"""API 요청과 응답의 형식. 업무 규칙은 domain에서 검증한다."""

# 표준 라이브러리
from uuid import UUID
from typing import Annotated

# 외부 라이브러리
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from app.outfits.domain.models import Activity, AvoidItem, ClothingPreference, ColdSensitivity, OutfitPreferences, OutfitStyle
from app.users.application.dto import AccountDTO, RecommendationProfile
from app.weather.presentation.schemas import LocationResponse


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


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=128)


class RegisterRequest(LoginRequest):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    password: SecretStr = Field(min_length=10, max_length=128, description="10~128자. 앞뒤 공백도 비밀번호에 포함")


class PreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cold_sensitivity: ColdSensitivity = ColdSensitivity.NORMAL
    style: OutfitStyle = OutfitStyle.DEFAULT
    activity: Activity = Activity.DAILY
    clothing_preference: ClothingPreference = ClothingPreference.ANY
    avoid_items: list[AvoidItem] = Field(default_factory=list, max_length=6)

    def to_domain(self) -> OutfitPreferences:
        return OutfitPreferences(self.cold_sensitivity, self.style, self.activity, self.clothing_preference, tuple(self.avoid_items))


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    location_id: int | None = Field(default=None, gt=0, strict=True, description="지역 검색에서 선택한 식별자")
    preferences: PreferencesRequest

    def to_domain(self) -> RecommendationProfile:
        return RecommendationProfile(self.location_id, self.preferences.to_domain())


class ProfileResponse(BaseModel):
    location: LocationResponse | None
    preferences: PreferencesRequest


class AccountResponse(BaseModel):
    user: UserResponse
    profile: ProfileResponse

    @classmethod
    def from_account(cls, account: AccountDTO) -> "AccountResponse":
        from dataclasses import asdict
        return cls(user=UserResponse.model_validate(account.user), profile=ProfileResponse(
            location=LocationResponse.model_validate(account.location) if account.location else None,
            preferences=PreferencesRequest.model_validate(asdict(account.preferences)),
        ))
