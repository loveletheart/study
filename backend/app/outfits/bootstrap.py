import hashlib
import json
from functools import lru_cache

from app.common.config import Settings, get_settings
from app.outfits.application.fallback import FallbackOutfitRecommender
from app.outfits.application.ports import OutfitRecommender
from app.outfits.application.services import OutfitService
from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.ollama_recommender import OllamaOutfitRecommender
from app.outfits.infrastructure.gemini_client import GeminiClient
from app.outfits.infrastructure.gemini_recommender import GeminiOutfitRecommender
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.outfits.infrastructure.prompts import PROMPT_VERSION
from app.outfits.infrastructure.result_cache import CachedOutfitService
from app.weather.bootstrap import get_weather_service


def _local_recommender(settings: Settings, timeout_seconds: float) -> OutfitRecommender:
    """로컬 추천 클라이언트 구성"""
    client = OllamaClient(settings.llm_base_url, timeout_seconds, settings.llm_context_size)
    return OllamaOutfitRecommender(client, settings.llm_model)


def _cloud_recommender(settings: Settings) -> OutfitRecommender:
    """클라우드 전환 시에만 Gemini 설정을 확인하고 추천 구현을 생성한다."""
    client = GeminiClient(settings.gemini_api_key, settings.gemini_timeout_seconds, settings.gemini_max_output_tokens)
    return GeminiOutfitRecommender(client, settings.gemini_model)


def get_outfit_service() -> OutfitService:
    """날씨 조회와 로컬 우선 추천 구현 연결"""
    settings = get_settings()
    if settings.cloud_fallback_enabled:
        timeout = settings.llm_timeout_seconds
        if settings.fallback_local_timeout_seconds is not None:
            timeout = min(timeout, settings.fallback_local_timeout_seconds)
        recommender: OutfitRecommender = FallbackOutfitRecommender(
            lambda: _local_recommender(settings, timeout), lambda: _cloud_recommender(settings),
        )
    else:
        recommender = _local_recommender(settings, settings.llm_timeout_seconds)
    return OutfitService(WeatherServiceReader(get_weather_service()), recommender)


@lru_cache
def get_cached_outfit_service() -> CachedOutfitService:
    """같은 모델·프롬프트 설정의 추천을 서버 재시작 후에도 공유"""
    settings = get_settings()
    signature = json.dumps([
        "outfit-cache-v1", PROMPT_VERSION, settings.llm_base_url, settings.llm_model,
        settings.llm_context_size, settings.cloud_fallback_enabled, settings.gemini_model,
        settings.gemini_max_output_tokens,
    ])
    scope = hashlib.sha256(signature.encode()).hexdigest()
    return CachedOutfitService(
        settings.database_path, scope, get_outfit_service, settings.outfit_refresh_seconds,
    )
