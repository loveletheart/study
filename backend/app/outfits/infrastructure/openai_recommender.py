from app.outfits.application.exceptions import OutfitCloudNotConfiguredError, OutfitCloudResponseError
from app.outfits.infrastructure.openai_client import OpenAIClient
from app.outfits.infrastructure.structured_recommender import StructuredOutfitRecommender


class OpenAIOutfitRecommender(StructuredOutfitRecommender):
    def __init__(self, client: OpenAIClient, model: str) -> None:
        """OpenAI 응답에 공통 추천 검증 적용"""
        super().__init__(client, model, "openai", OutfitCloudResponseError, OutfitCloudNotConfiguredError)
