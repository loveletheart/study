"""트랜잭션을 커밋하고, 커밋되지 않은 작업은 롤백한 뒤 연결을 닫는다."""

from pathlib import Path
from types import TracebackType

from app.common.database import connect_database
from app.users.application.unit_of_work import UserUnitOfWork
from app.users.infrastructure.repositories import SQLiteUserRepository


class SQLiteUserUnitOfWork(UserUnitOfWork):
    # DB 경로 보관
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    # DB 연결과 저장소 준비
    def __enter__(self) -> "SQLiteUserUnitOfWork":
        self._connection = connect_database(self._database_path)
        self.users = SQLiteUserRepository(self._connection)
        return self

    # 미커밋 변경 롤백 후 연결 종료
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self._connection.rollback()
        finally:
            self._connection.close()

    # 변경 사항 커밋
    def commit(self) -> None:
        self._connection.commit()
