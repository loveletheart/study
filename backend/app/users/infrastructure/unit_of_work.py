"""트랜잭션을 커밋하고, 커밋되지 않은 작업은 롤백한 뒤 연결을 닫는다."""

# 표준 라이브러리
from pathlib import Path
from types import TracebackType

# 프로젝트 모듈
from app.common.database import connect_database
from app.users.application.unit_of_work import UserUnitOfWork
from app.users.infrastructure.repositories import SQLiteUserRepository


class SQLiteUserUnitOfWork(UserUnitOfWork):
    def __init__(self, database_path: Path) -> None:
        """DB 경로 보관"""
        self._database_path = database_path

    def __enter__(self) -> "SQLiteUserUnitOfWork":
        """DB 연결과 저장소 준비"""
        self._connection = connect_database(self._database_path)
        self.users = SQLiteUserRepository(self._connection)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """미커밋 변경 롤백 후 연결 종료"""
        try:
            self._connection.rollback()
        finally:
            self._connection.close()

    def commit(self) -> None:
        """변경 사항 커밋"""
        self._connection.commit()
