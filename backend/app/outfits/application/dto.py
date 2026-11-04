from dataclasses import dataclass
from datetime import date, datetime

from app.outfits.domain.models import OutfitRecommendation, OutfitWeather, WeeklyWardrobe


@dataclass(frozen=True)
class OutfitCoordinates:
    latitude: float
    longitude: float


@dataclass(frozen=True)
class OutfitForecast:
    coordinates: OutfitCoordinates
    timezone: str
    fetched_at: datetime
    provider: str
    source_url: str
    today: date
    days: tuple[OutfitWeather, ...]


@dataclass(frozen=True)
class TodayOutfitResult:
    forecast: OutfitForecast
    recommendation: OutfitRecommendation


@dataclass(frozen=True)
class WeeklyOutfitResult:
    forecast: OutfitForecast
    daily: tuple[OutfitRecommendation, ...]
    wardrobe: WeeklyWardrobe
    summary: str
