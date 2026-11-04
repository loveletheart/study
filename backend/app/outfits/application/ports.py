from typing import Protocol

from app.outfits.application.dto import OutfitForecast


class OutfitWeatherReader(Protocol):
    def get_forecast(self, latitude: float, longitude: float) -> OutfitForecast:
        """옷차림 판단에 필요한 7일 예보 조회 계약"""
        ...
