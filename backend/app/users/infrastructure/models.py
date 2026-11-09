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
    "CREATE TABLE IF NOT EXISTS user_sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL)",
    "CREATE TABLE IF NOT EXISTS user_recommendation_profiles (user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, payload BLOB NOT NULL)",
    "CREATE TABLE IF NOT EXISTS auth_rate_limits (bucket TEXT PRIMARY KEY, window_start REAL NOT NULL, attempts INTEGER NOT NULL)",
)

# 검증 테스트
def user_from_row(row: sqlite3.Row) -> User:
    """DB 조회 행을 사용자 객체로 변환"""
    return User(id=UUID(row["id"]), name=row["name"], email=row["email"])
