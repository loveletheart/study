"""SQLite 연결과 개발용 스키마 초기화. 요청마다 별도의 연결을 사용한다."""

# 표준 라이브러리
import sqlite3
from contextlib import closing
from pathlib import Path

# 프로젝트 모듈
from app.common.config import get_settings


def connect_database(database_path: Path | None = None) -> sqlite3.Connection:
    """SQLite 연결 생성"""
    path = database_path if database_path is not None else get_settings().database_path
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: Path | None = None) -> None:
    """테이블이 없으면 생성"""
    # 업무별 테이블 정의는 해당 업무의 infrastructure에서 관리한다.
    from app.users.infrastructure.models import CREATE_USERS_TABLE

    with closing(connect_database(database_path)) as connection, connection:
        connection.execute(CREATE_USERS_TABLE)
