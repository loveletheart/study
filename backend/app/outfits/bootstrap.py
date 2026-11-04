from app.outfits.application.services import OutfitService
from app.outfits.infrastructure.weather_reader import WeatherServiceReader
from app.weather.bootstrap import get_weather_service


def get_outfit_service() -> OutfitService:
    """기존 날씨 조회와 옷차림 서비스 연결"""
    return OutfitService(WeatherServiceReader(get_weather_service()))
