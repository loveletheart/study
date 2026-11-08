"""사용자 저장소의 SQLite 구현. 커밋은 하지 않는다."""

# 표준 라이브러리
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID
from pydantic import TypeAdapter
from app.common.database import connect_database
from app.users.application.dto import RecommendationProfile
from app.users.application.exceptions import AuthenticationRateLimitError

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


PROFILE_ADAPTER = TypeAdapter(RecommendationProfile)


class SQLiteAuthRepository:
    def __init__(self, database_path: Path) -> None:
        self._path = database_path

    def create_account(self, user: User, password_hash: str) -> None:
        """계정 기본 정보와 로그인 자격 증명을 함께 저장한다."""
        with closing(connect_database(self._path)) as connection, connection:
            SQLiteUserRepository(connection).add(user)
            connection.execute("INSERT INTO user_credentials VALUES (?, ?)", (str(user.id), password_hash))

    def credentials(self, email: str) -> tuple[User, str] | None:
        with closing(connect_database(self._path)) as connection:
            row = connection.execute("SELECT u.id, u.name, u.email, c.password_hash FROM users u JOIN user_credentials c ON u.id=c.user_id WHERE u.email=?", (email,)).fetchone()
        return (user_from_row(row), row["password_hash"]) if row else None

    def create_session(self, user_id: UUID, token_hash: str, expires_at: float, now: float, previous_hash: str | None) -> None:
        """만료 세션을 정리하고 현재 브라우저의 이전 세션은 교체한다."""
        with closing(connect_database(self._path)) as connection, connection:
            connection.execute("DELETE FROM user_sessions WHERE expires_at<=? OR token_hash=?", (now, previous_hash))
            connection.execute("INSERT INTO user_sessions VALUES (?, ?, ?)", (token_hash, str(user_id), expires_at))

    def session_user(self, token_hash: str, now: float) -> User | None:
        with closing(connect_database(self._path)) as connection:
            row = connection.execute("SELECT u.id, u.name, u.email FROM user_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?", (token_hash, now)).fetchone()
        return user_from_row(row) if row else None

    def delete_session(self, token_hash: str) -> None:
        with closing(connect_database(self._path)) as connection, connection:
            connection.execute("DELETE FROM user_sessions WHERE token_hash=?", (token_hash,))

    def profile(self, user_id: UUID) -> RecommendationProfile:
        with closing(connect_database(self._path)) as connection:
            row = connection.execute("SELECT payload FROM user_recommendation_profiles WHERE user_id=?", (str(user_id),)).fetchone()
        return PROFILE_ADAPTER.validate_json(row["payload"]) if row else RecommendationProfile()

    def save_profile(self, user: User, profile: RecommendationProfile) -> None:
        with closing(connect_database(self._path)) as connection, connection:
            connection.execute("UPDATE users SET name=? WHERE id=?", (user.name, str(user.id)))
            connection.execute("INSERT INTO user_recommendation_profiles VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload", (str(user.id), PROFILE_ADAPTER.dump_json(profile)))

    def consume_attempts(self, buckets: tuple[tuple[str, int], ...], now: float) -> None:
        """동시 요청·서버 재시작에도 유지되는 15분 단위 인증 요청 제한."""
        with closing(connect_database(self._path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM auth_rate_limits WHERE window_start<=?", (now - 900,))
            for bucket, limit in buckets:
                row = connection.execute("SELECT attempts FROM auth_rate_limits WHERE bucket=?", (bucket,)).fetchone()
                if row and row["attempts"] >= limit:
                    raise AuthenticationRateLimitError()
            for bucket, _ in buckets:
                connection.execute("INSERT INTO auth_rate_limits VALUES (?, ?, 1) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1", (bucket, now))
