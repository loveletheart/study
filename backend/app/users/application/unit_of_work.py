"""애플리케이션이 필요한 트랜잭션 기능. DB 구현은 알지 못한다."""

from abc import ABC, abstractmethod
from types import TracebackType

from app.users.domain.repositories import UserRepository


class UserUnitOfWork(ABC):
    users: UserRepository

    @abstractmethod
    def __enter__(self) -> "UserUnitOfWork": ...

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    @abstractmethod
    def commit(self) -> None: ...
