"""사용자 테이블 정의와 DB 행을 도메인 객체로 변환하는 매핑."""


# 표준 라이브러리
import sqlite3
from uuid import UUID

# 프로젝트 모듈
from app.users.domain.entities import User


# 테이블 생성 SQL
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 100),
    email TEXT NOT NULL CHECK(length(email) <= 254),
    CONSTRAINT uq_users_email UNIQUE(email)
)
"""

AUTH_TABLES = (
    "CREATE TABLE IF NOT EXISTS user_credentials (user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, password_hash TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS user_sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL, last_active_at REAL NOT NULL)",
    "CREATE TABLE IF NOT EXISTS user_recommendation_profiles (user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, payload BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS auth_rate_limits (bucket TEXT PRIMARY KEY, window_start REAL NOT NULL, attempts INTEGER NOT NULL)",
)
LEGACY_SESSION_LIFETIME_SECONDS = 7 * 86400


def initialize_auth_tables(connection: sqlite3.Connection, session_max_age_seconds: int) -> None:
    """이전 세션의 마지막 활동을 초기화하고 최대 유지 시간을 적용한다."""
    for statement in AUTH_TABLES:
        connection.execute(statement)
    session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(user_sessions)")}
    if "last_active_at" not in session_columns:
        connection.execute("ALTER TABLE user_sessions ADD COLUMN last_active_at REAL NOT NULL DEFAULT 0")
        # 이전 7일 만료 시각으로 발급 시각을 복원하고 기존 만료보다 늦어지지 않게 한다.
        connection.execute(
            "UPDATE user_sessions SET last_active_at = expires_at - ?, "
            "expires_at = MIN(expires_at, expires_at - ? + ?)",
            (LEGACY_SESSION_LIFETIME_SECONDS, LEGACY_SESSION_LIFETIME_SECONDS, session_max_age_seconds),
        )


def user_from_row(row: sqlite3.Row) -> User:
    """DB 조회 행을 사용자 객체로 변환"""
    return User(id=UUID(row["id"]), name=row["name"], email=row["email"])
