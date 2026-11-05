from app.common.config import Settings, get_settings
from app.outfits.application.fallback import FallbackOutfitRecommender
from app.outfits.application.ports import OutfitRecommender
from app.outfits.application.services import OutfitService
from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.ollama_recommender import OllamaOutfitRecommender
from app.outfits.infrastructure.openai_client import OpenAIClient
from app.outfits.infrastructure.openai_recommender import OpenAIOutfitRecommender
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.weather.bootstrap import get_weather_service


def _local_recommender(settings: Settings, timeout_seconds: float) -> OutfitRecommender:
    """로컬 추천 클라이언트 구성"""
    client = OllamaClient(settings.llm_base_url, timeout_seconds, settings.llm_context_size)
    return OllamaOutfitRecommender(client, settings.llm_model)


def _cloud_recommender(settings: Settings) -> OutfitRecommender:
    """클라우드 전환 시에만 OpenAI 설정 확인"""
    client = OpenAIClient(settings.openai_api_key, settings.openai_timeout_seconds, settings.openai_max_output_tokens)
    return OpenAIOutfitRecommender(client, settings.openai_model)


def get_outfit_service() -> OutfitService:
    """날씨 조회와 로컬 우선 추천 구현 연결"""
    settings = get_settings()
    if settings.cloud_fallback_enabled:
        timeout = min(settings.llm_timeout_seconds, settings.fallback_local_timeout_seconds)
        recommender: OutfitRecommender = FallbackOutfitRecommender(
            lambda: _local_recommender(settings, timeout), lambda: _cloud_recommender(settings),
        )
    else:
        recommender = _local_recommender(settings, settings.llm_timeout_seconds)
    return OutfitService(WeatherServiceReader(get_weather_service()), recommender)
