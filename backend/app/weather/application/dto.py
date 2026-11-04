from dataclasses import dataclass

from app.weather.domain.models import DailyForecast, HourlyForecast, Location, WeatherForecast


@dataclass(frozen=True)
class LocationSearchResult:
    locations: tuple[Location, ...]
    attribution: str = "Location data by Open-Meteo and GeoNames"


@dataclass(frozen=True)
class TodayWeatherResult:
    forecast: WeatherForecast
    today: DailyForecast
    hourly: tuple[HourlyForecast, ...]
    summary: str
