"""HTTP 스키마와 분리한 애플리케이션 입력·출력 데이터."""

# 표준 라이브러리
from dataclasses import dataclass
from uuid import UUID

# 프로젝트 모듈
from app.users.domain.entities import User
from app.outfits.domain.models import OutfitPreferences
from app.weather.domain.models import Location


@dataclass(frozen=True)
class CreateUserCommand:
    name: str
    email: str


@dataclass(frozen=True)
class UserDTO:
    id: UUID
    name: str
    email: str

    @classmethod
    def from_entity(cls, user: User) -> "UserDTO":
        """사용자 객체를 응답 DTO로 변환"""
        return cls(id=user.id, name=user.name, email=user.email)


@dataclass(frozen=True)
class RecommendationProfile:
    location_id: int | None = None
    preferences: OutfitPreferences = OutfitPreferences()


@dataclass(frozen=True)
class AccountDTO:
    user: UserDTO
    location: Location | None
    preferences: OutfitPreferences
