# 표준 라이브러리
from dataclasses import dataclass

# 프로젝트 모듈
from app.weather.domain.models import DailyForecast, HourlyForecast, Location, WeatherForecast


@dataclass(frozen=True)
class LocationSearchResult:
    locations: tuple[Location, ...]
    attribution: str = "Location data by Open-Meteo and GeoNames"
    total: int | None = None
    offset: int = 0
    limit: int = 5
    has_more: bool = False


@dataclass(frozen=True)
class TodayWeatherResult:
    forecast: WeatherForecast
    today: DailyForecast
    hourly: tuple[HourlyForecast, ...]
    summary: str
