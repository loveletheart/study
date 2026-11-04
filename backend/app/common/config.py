"""환경변수와 .env 파일에서 애플리케이션 설정을 읽는다."""

import os
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_path: Path
    weather_timeout_seconds: float = 10.0
    weather_cache_ttl_seconds: float = 600.0
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = ""
    llm_timeout_seconds: float = 180.0
    llm_context_size: int = 16384


def _number_setting(values: dict, key: str, default: float, minimum: float, maximum: float) -> float:
    """숫자 설정값과 허용 범위 검증"""
    try:
        value = float(values.get(key) or default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number.") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    return value


def _llm_base_url(value: str) -> str:
    """LLM 연결 주소의 HTTP 형식 검증"""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("STUDY_LLM_BASE_URL must be an HTTP(S) base URL without credentials or query.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("STUDY_LLM_BASE_URL has an invalid port.") from exc
    return value.rstrip("/")


def _context_size(values: dict) -> int:
    """LLM 문맥 길이의 정수 범위 검증"""
    value = _number_setting(values, "STUDY_LLM_CONTEXT_SIZE", 16384, 2048, 131072)
    if not value.is_integer():
        raise ValueError("STUDY_LLM_CONTEXT_SIZE must be an integer.")
    return int(value)


@lru_cache
def get_settings() -> Settings:
    """환경변수와 .env 설정 로드"""
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
        llm_base_url=_llm_base_url((values.get("STUDY_LLM_BASE_URL") or "http://127.0.0.1:11434").strip()),
        llm_model=(values.get("STUDY_LLM_MODEL") or "").strip(),
        llm_timeout_seconds=_number_setting(values, "STUDY_LLM_TIMEOUT_SECONDS", 180, 1, 600),
        llm_context_size=_context_size(values),
    )
