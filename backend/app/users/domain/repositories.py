"""사용자 저장소가 제공해야 하는 기능만 선언한다."""

# 표준 라이브러리
from typing import Protocol
from uuid import UUID

# 프로젝트 모듈
from app.users.domain.entities import User


class UserRepository(Protocol):
    def find_by_id(self, user_id: UUID) -> User | None:
        """UUID로 사용자 조회 계약"""
        ...

    def find_by_email(self, email: str) -> User | None:
        """이메일로 사용자 조회 계약"""
        ...

    def add(self, user: User) -> None:
        """사용자 저장 계약"""
        ...
