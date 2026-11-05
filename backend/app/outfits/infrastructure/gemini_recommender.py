from app.outfits.application.exceptions import OutfitCloudNotConfiguredError, OutfitCloudResponseError
from app.outfits.infrastructure.gemini_client import GeminiClient
from app.outfits.infrastructure.structured_recommender import StructuredOutfitRecommender


class GeminiOutfitRecommender(StructuredOutfitRecommender):
    def __init__(self, client: GeminiClient, model: str) -> None:
        """Gemini 응답에 공통 옷차림 검증과 클라우드 오류 처리를 적용한다."""
        super().__init__(client, model, "gemini", OutfitCloudResponseError, OutfitCloudNotConfiguredError)
