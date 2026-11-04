from functools import lru_cache

from app.common.config import get_settings
from app.weather.application.services import WeatherService
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.http_client import JsonHttpClient
from app.weather.infrastructure.open_meteo import OpenMeteoProvider


@lru_cache
def get_weather_provider() -> OpenMeteoProvider:
    """날씨 API 클라이언트와 캐시 구성"""
    settings = get_settings()
    return OpenMeteoProvider(
        http=JsonHttpClient(settings.weather_timeout_seconds),
        cache=TTLCache(settings.weather_cache_ttl_seconds),
    )


def get_weather_service() -> WeatherService:
    """날씨 제공사와 서비스 연결"""
    return WeatherService(get_weather_provider())
