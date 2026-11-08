"""사용자 저장소의 SQLite 구현. 커밋은 하지 않는다."""

# 표준 라이브러리
import sqlite3
from uuid import UUID

# 프로젝트 모듈
from app.users.domain.entities import User
from app.users.domain.exceptions import DuplicateEmailError
from app.users.infrastructure.models import user_from_row


class SQLiteUserRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        """DB 연결 주입"""
        self._connection = connection

    def find_by_id(self, user_id: UUID) -> User | None:
        """UUID 조건으로 사용자 조회"""
        row = self._connection.execute(
            "SELECT id, name, email FROM users WHERE id = ?", (str(user_id),)
        ).fetchone()
        return user_from_row(row) if row is not None else None

    def find_by_email(self, email: str) -> User | None:
        """이메일 조건으로 사용자 조회"""
        row = self._connection.execute(
            "SELECT id, name, email FROM users WHERE email = ?", (email,)
        ).fetchone()
        return user_from_row(row) if row is not None else None

    def add(self, user: User) -> None:
        """사용자 저장 및 이메일 중복 처리"""
        try:
            self._connection.execute(
                "INSERT INTO users (id, name, email) VALUES (?, ?, ?)",
                (str(user.id), user.name, user.email),
            )
        except sqlite3.IntegrityError as exc:
            # 동시 요청에서도 DB의 UNIQUE 제약으로 중복을 방지한다.
            if (
                exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE
                and "users.email" in str(exc)
            ):
                raise DuplicateEmailError() from exc
            raise
