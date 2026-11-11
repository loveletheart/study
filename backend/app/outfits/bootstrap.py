# 표준 라이브러리
import hashlib
import json
from functools import lru_cache

# 프로젝트 모듈
from app.common.config import Settings, get_settings
from app.outfits.application.policies import FallbackOutfitRecommender
from app.outfits.application.ports import OutfitRecommender
from app.outfits.application.exceptions import OutfitCloudNotConfiguredError, OutfitCloudResponseError
from app.outfits.application.services import OutfitService, RegionOutfitService
from app.outfits.infrastructure.clients import OllamaClient, GeminiClient
from app.outfits.infrastructure.recommenders import (
    OllamaOutfitRecommender,
    GeminiOutfitRecommender,
    LlmOutfitPersonalizer,
    PersonalizationChatClient,
    StructuredOutfitRecommender,
)
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.outfits.infrastructure.prompts import PERSONALIZATION_VERSION, PROMPT_VERSION
from app.outfits.infrastructure.cache import CachedOutfitService, SQLitePersonalizedOutfitCache
from app.outfits.infrastructure.jobs import WeeklyOutfitBatch
from app.outfits.domain.models import OutfitPreferences
from app.outfits.feedback_bootstrap import feedback_store_for_path
from app.outfits.infrastructure.feedback import RecordingChatClient
from app.weather.bootstrap import get_location_catalog, get_sigungu_resolver, get_weather_service


def _sampling_options(settings: Settings) -> dict:
    """생성 클라이언트와 캐시가 같은 샘플링 설정을 사용한다."""
    return {"temperature": settings.llm_temperature, "top_p": settings.llm_top_p, "min_p": settings.llm_min_p}


def _cache_scope(settings: Settings, version: str) -> str:
    """기존 순서를 유지해 공통·개인 캐시가 같은 생성 설정을 구분한다."""
    signature = json.dumps([
        version, PROMPT_VERSION, settings.llm_base_url, settings.llm_model,
        settings.llm_context_size, settings.cloud_fallback_enabled, settings.gemini_model,
        settings.llm_today_context_size, settings.llm_thinking, settings.gemini_max_output_tokens,
        _sampling_options(settings),
    ])
    return hashlib.sha256(signature.encode()).hexdigest()


def _local_timeout(settings: Settings) -> float:
    """공통·개인 추천에 같은 로컬 대기 제한을 적용한다."""
    timeout = settings.llm_timeout_seconds
    if not settings.cloud_fallback_enabled:
        return timeout
    fallback_timeout = settings.fallback_local_timeout_seconds
    return min(timeout, fallback_timeout if fallback_timeout is not None else 20.0)


def _local_recommender(
    settings: Settings, timeout_seconds: float, preferences: OutfitPreferences | None = None,
) -> OutfitRecommender:
    """공통·개인 추천의 로컬 클라이언트를 같은 설정으로 구성한다."""
    client = OllamaClient(
        settings.llm_base_url, timeout_seconds, settings.llm_context_size,
        today_context_size=settings.llm_today_context_size,
        thinking=settings.llm_thinking,
        **_sampling_options(settings),
    )
    recorded = RecordingChatClient(client, feedback_store_for_path(settings.database_path), "ollama")
    if preferences is None:
        return OllamaOutfitRecommender(
            recorded, settings.llm_model, repair_attempts=1,
            retry_on_timeout=settings.cloud_fallback_enabled,
        )
    return StructuredOutfitRecommender(
        PersonalizationChatClient(recorded, preferences), settings.llm_model, "ollama", repair_attempts=1,
        retry_on_timeout=settings.cloud_fallback_enabled,
    )


def _cloud_recommender(settings: Settings, preferences: OutfitPreferences | None = None) -> OutfitRecommender:
    """클라우드 전환 시에만 Gemini 설정을 확인하고 추천 구현을 생성한다."""
    client = GeminiClient(settings.gemini_api_key, settings.gemini_timeout_seconds, settings.gemini_max_output_tokens)
    recorded = RecordingChatClient(client, feedback_store_for_path(settings.database_path), "gemini")
    if preferences is None:
        return GeminiOutfitRecommender(recorded, settings.gemini_model)
    return StructuredOutfitRecommender(
        PersonalizationChatClient(recorded, preferences), settings.gemini_model, "gemini",
        OutfitCloudResponseError, OutfitCloudNotConfiguredError,
    )


def get_outfit_service() -> OutfitService:
    """날씨 조회와 로컬 우선 추천 구현 연결"""
    settings = get_settings()
    timeout = _local_timeout(settings)
    if settings.cloud_fallback_enabled:
        recommender: OutfitRecommender = FallbackOutfitRecommender(
            lambda: _local_recommender(settings, timeout), lambda: _cloud_recommender(settings),
        )
    else:
        recommender = _local_recommender(settings, timeout)
    return OutfitService(WeatherServiceReader(get_weather_service()), recommender)


@lru_cache
def get_cached_outfit_service() -> CachedOutfitService:
    """같은 모델·프롬프트 설정의 추천을 서버 재시작 후에도 공유"""
    settings = get_settings()
    return CachedOutfitService(
        settings.database_path, _cache_scope(settings, "outfit-cache-v2-sigungu"),
        get_outfit_service, settings.outfit_refresh_seconds,
        reuse_unchanged_weather=True,
        max_entries=settings.outfit_cache_max_entries,
        weekly_batch_only=True, weekly_batch_hour=settings.outfit_weekly_batch_hour,
        weekly_max_age_seconds=settings.outfit_weekly_max_age_seconds,
    )


def get_region_outfit_service() -> RegionOutfitService:
    """대표 지역 기준의 공유 추천과 요청별 개인화 조립"""
    return RegionOutfitService(
        get_location_catalog(), get_cached_outfit_service(), get_personalized_outfit_cache(), get_sigungu_resolver(),
    )


def _personal_recommender(preferences: OutfitPreferences) -> OutfitRecommender:
    """개인화에도 로컬 우선과 명시적 클라우드 전환 정책 적용"""
    settings = get_settings()

    timeout = _local_timeout(settings)
    if settings.cloud_fallback_enabled:
        return FallbackOutfitRecommender(
            lambda: _local_recommender(settings, timeout, preferences),
            lambda: _cloud_recommender(settings, preferences),
        )
    return _local_recommender(settings, timeout, preferences)


@lru_cache
def get_personalized_outfit_cache() -> SQLitePersonalizedOutfitCache:
    """개인 조건의 동적 결과와 사전 생성 대상을 서버 수명 동안 공유"""
    settings = get_settings()
    return SQLitePersonalizedOutfitCache(
        settings.database_path, _cache_scope(settings, PERSONALIZATION_VERSION),
        LlmOutfitPersonalizer(_personal_recommender),
        get_cached_outfit_service(), get_sigungu_resolver(), max_entries=settings.outfit_cache_max_entries,
        weekly_batch_only=True,
    )


def get_weekly_outfit_batch() -> WeeklyOutfitBatch:
    """주간 전용 일일 배치 구성"""
    return WeeklyOutfitBatch(get_cached_outfit_service(), get_personalized_outfit_cache())
