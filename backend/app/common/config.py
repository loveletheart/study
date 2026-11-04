"""환경변수와 .env 파일에서 애플리케이션 설정을 읽는다."""

import os
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_path: Path
    weather_timeout_seconds: float = 10.0
    weather_cache_ttl_seconds: float = 600.0


def _number_setting(values: dict, key: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(values.get(key) or default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number.") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return value


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
        weather_timeout_seconds=_number_setting(values, "STUDY_WEATHER_TIMEOUT_SECONDS", 10, 0.1, 30),
        weather_cache_ttl_seconds=_number_setting(values, "STUDY_WEATHER_CACHE_TTL_SECONDS", 600, 0, 3600),
    )
