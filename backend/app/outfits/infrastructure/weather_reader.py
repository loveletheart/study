# 프로젝트 모듈
from app.outfits.application.dto import OutfitCoordinates, OutfitForecast
from app.outfits.application.exceptions import OutfitForecastError
from app.outfits.domain.models import OutfitWeather
from app.weather.application.services import WeatherService
from app.weather.domain.models import KST


class WeatherServiceReader:
    def __init__(self, service: WeatherService) -> None:
        """기존 날씨 서비스 주입"""
        self._service = service

    def get_forecast(self, latitude: float, longitude: float) -> OutfitForecast:
        """날씨 예보를 옷차림 판단 정보로 변환"""
        forecast = self._service.get_weekly(latitude, longitude)
        try:
            days = tuple(OutfitWeather(
                date=day.date,
                temperature_min_c=day.temperature_min_c,
                temperature_max_c=day.temperature_max_c,
                apparent_temperature_min_c=day.apparent_temperature_min_c,
                apparent_temperature_max_c=day.apparent_temperature_max_c,
                precipitation_probability_percent=day.precipitation_probability_max_percent,
                precipitation_mm=day.precipitation_sum_mm,
                snowfall_cm=day.snowfall_sum_cm,
                wind_speed_m_s=day.wind_speed_max_m_s,
                uv_index=day.uv_index_max,
                weather_code=day.weather_code,
                description=day.description,
            ) for day in forecast.daily)
        except (TypeError, ValueError) as exc:
            raise OutfitForecastError() from exc
        return OutfitForecast(
            coordinates=OutfitCoordinates(forecast.coordinates.latitude, forecast.coordinates.longitude),
            timezone=forecast.timezone, fetched_at=forecast.fetched_at,
            provider=forecast.provider, source_url=forecast.source_url,
            today=forecast.fetched_at.astimezone(KST).date(), days=days,
        )
