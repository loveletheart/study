from app.outfits.infrastructure.ollama_client import OllamaClient
from app.outfits.infrastructure.structured_recommender import StructuredOutfitRecommender


class OllamaOutfitRecommender(StructuredOutfitRecommender):
    def __init__(self, client: OllamaClient, model: str) -> None:
        """Ollama 응답에 공통 추천 검증 적용"""
        super().__init__(client, model, "ollama")
