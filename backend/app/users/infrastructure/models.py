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


def initialize_auth_tables(connection: sqlite3.Connection) -> None:
    """기존 계정과 세션을 보존하며 마지막 활동 시각을 추가한다."""
    for statement in AUTH_TABLES:
        connection.execute(statement)
    session_columns = {row["name"] for row in connection.execute("PRAGMA table_info(user_sessions)")}
    if "last_active_at" not in session_columns:
        connection.execute("ALTER TABLE user_sessions ADD COLUMN last_active_at REAL NOT NULL DEFAULT 0")
        # 이전 스키마에서는 발급 후 정확히 7일이 지나면 만료됐다.
        connection.execute("UPDATE user_sessions SET last_active_at = expires_at - ?", (7 * 86400,))


def user_from_row(row: sqlite3.Row) -> User:
    """DB 조회 행을 사용자 객체로 변환"""
    return User(id=UUID(row["id"]), name=row["name"], email=row["email"])
