"""HTTP 스키마와 분리한 애플리케이션 입력·출력 데이터."""

from dataclasses import dataclass
from uuid import UUID

from app.users.domain.entities import User


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
        return cls(id=user.id, name=user.name, email=user.email)
