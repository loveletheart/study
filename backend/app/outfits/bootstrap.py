from app.common.config import get_settings
from app.outfits.application.services import OutfitService
from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.ollama_recommender import OllamaOutfitRecommender
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.weather.bootstrap import get_weather_service


def get_outfit_service() -> OutfitService:
    """날씨 조회와 로컬 LLM 추천 구현 연결"""
    settings = get_settings()
    client = OllamaClient(settings.llm_base_url, settings.llm_timeout_seconds, settings.llm_context_size)
    recommender = OllamaOutfitRecommender(client, settings.llm_model)
    return OutfitService(WeatherServiceReader(get_weather_service()), recommender)
