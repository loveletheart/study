"""환경변수와 .env 파일에서 애플리케이션 설정을 읽는다."""


# 표준 라이브러리
import os
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

# 외부 라이브러리
from dotenv import dotenv_values


# 프로젝트 경로
PROJECT_ROOT = Path(__file__).resolve().parents[3]


# 애플리케이션 설정
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
    llm_today_context_size: int = 4096
    llm_thinking: bool | None = None
    llm_temperature: float = 0.3
    llm_top_p: float | None = None
    llm_min_p: float | None = None
    cloud_fallback_enabled: bool = False
    fallback_local_timeout_seconds: float | None = None
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = ""
    gemini_timeout_seconds: float = 60.0
    gemini_max_output_tokens: int = 8192
    outfit_refresh_seconds: float = 3600.0
    outfit_cache_max_entries: int = 4096
    outfit_weekly_batch_hour: int = 1
    outfit_weekly_max_age_seconds: float = 172800.0
    vworld_api_key: str = field(default="", repr=False)
    vworld_domain: str = ""
    session_cookie_secure: bool = False


# 설정값 검증
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


def _integer_setting(values: dict, key: str, default: int, minimum: int, maximum: int) -> int:
    """정수 설정값과 허용 범위 검증"""
    value = _number_setting(values, key, default, minimum, maximum)
    if not value.is_integer():
        raise ValueError(f"{key} must be an integer.")
    return int(value)


def _optional_probability(values: dict, key: str) -> float | None:
    raw = values.get(key)
    if raw is None or not str(raw).strip():
        return None
    return _number_setting(values, key, 0, 0, 1)


def _boolean_setting(values: dict, key: str, default: bool = False) -> bool:
    """명시적으로 지정한 불리언 설정 검증"""
    raw = str(values.get(key) or str(default)).strip().lower()
    if raw not in {"true", "false"}:
        raise ValueError(f"{key} must be true or false.")
    return raw == "true"


# 설정 로드
@lru_cache
def get_settings() -> Settings:
    """환경변수와 .env 설정 로드"""
    # .env에 작성한 값을 우선하고, 없는 항목은 환경변수와 기본값을 사용한다.
    values = {**os.environ, **dotenv_values(PROJECT_ROOT / ".env")}
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
        llm_context_size=_integer_setting(values, "STUDY_LLM_CONTEXT_SIZE", 16384, 2048, 131072),
        llm_today_context_size=_integer_setting(values, "STUDY_LLM_TODAY_CONTEXT_SIZE", 4096, 2048, 131072),
        llm_thinking=(
            _boolean_setting(values, "STUDY_LLM_THINKING")
            if str(values.get("STUDY_LLM_THINKING") or "").strip() else None
        ),
        llm_temperature=_number_setting(values, "STUDY_LLM_TEMPERATURE", 0.3, 0, 2),
        llm_top_p=_optional_probability(values, "STUDY_LLM_TOP_P"),
        llm_min_p=_optional_probability(values, "STUDY_LLM_MIN_P"),
        cloud_fallback_enabled=_boolean_setting(values, "STUDY_LLM_CLOUD_FALLBACK_ENABLED"),
        fallback_local_timeout_seconds=(
            _number_setting(values, "STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS", 180, 1, 600)
            if str(values.get("STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS") or "").strip() else None
        ),
        gemini_api_key=(values.get("GEMINI_API_KEY") or "").strip(),
        gemini_model=(values.get("STUDY_GEMINI_MODEL") or "").strip(),
        gemini_timeout_seconds=_number_setting(values, "STUDY_GEMINI_TIMEOUT_SECONDS", 60, 1, 300),
        gemini_max_output_tokens=_integer_setting(values, "STUDY_GEMINI_MAX_OUTPUT_TOKENS", 8192, 128, 32768),
        outfit_refresh_seconds=_number_setting(values, "STUDY_OUTFIT_REFRESH_SECONDS", 3600, 60, 86400),
        outfit_cache_max_entries=_integer_setting(values, "STUDY_OUTFIT_CACHE_MAX_ENTRIES", 4096, 1, 100000),
        outfit_weekly_batch_hour=_integer_setting(values, "STUDY_OUTFIT_WEEKLY_BATCH_HOUR", 1, 0, 23),
        outfit_weekly_max_age_seconds=_number_setting(values, "STUDY_OUTFIT_WEEKLY_MAX_AGE_SECONDS", 172800, 86400, 604800),
        vworld_api_key=(values.get("VWORLD_API_KEY") or "").strip(),
        vworld_domain=(values.get("STUDY_VWORLD_DOMAIN") or "").strip(),
        session_cookie_secure=_boolean_setting(values, "STUDY_SESSION_COOKIE_SECURE"),
    )
