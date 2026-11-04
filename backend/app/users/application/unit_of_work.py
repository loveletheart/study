"""애플리케이션이 필요한 트랜잭션 기능. DB 구현은 알지 못한다."""

from abc import ABC, abstractmethod
from types import TracebackType

from app.users.domain.repositories import UserRepository


class UserUnitOfWork(ABC):
    users: UserRepository

    @abstractmethod
    def __enter__(self) -> "UserUnitOfWork":
        """작업 범위 시작 계약"""
        ...

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """작업 종료와 자원 정리 계약"""
        ...

    @abstractmethod
    def commit(self) -> None:
        """변경 사항 확정 계약"""
        ...
