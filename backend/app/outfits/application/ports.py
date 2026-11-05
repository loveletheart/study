from typing import Protocol

from app.outfits.application.dto import GeneratedOutfits, OutfitForecast
from app.outfits.domain.models import OutfitWeather


class OutfitWeatherReader(Protocol):
    def get_forecast(self, latitude: float, longitude: float) -> OutfitForecast:
        """옷차림 판단에 필요한 7일 예보 조회 계약"""
        ...


class OutfitRecommender(Protocol):
    def recommend(self, days: tuple[OutfitWeather, ...]) -> GeneratedOutfits:
        """날짜별 날씨에 맞는 옷차림 생성 계약"""
        ...
