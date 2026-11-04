"""환경변수와 .env 파일에서 애플리케이션 설정을 읽는다."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_path: Path


@lru_cache
def get_settings() -> Settings:
    # 실제 환경변수가 .env보다 우선한다. .env가 없어도 기본값으로 실행한다.
    values = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
    database_path = Path(values.get("STUDY_DATABASE_PATH") or "study.db")
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    return Settings(
        app_name=values.get("STUDY_APP_NAME") or "Study API",
        database_path=database_path,
    )
