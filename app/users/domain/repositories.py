"""사용자 저장소가 제공해야 하는 기능만 선언한다."""

from typing import Protocol
from uuid import UUID

from app.users.domain.entities import User


class UserRepository(Protocol):
    def find_by_id(self, user_id: UUID) -> User | None: ...

    def find_by_email(self, email: str) -> User | None: ...

    def add(self, user: User) -> None: ...
