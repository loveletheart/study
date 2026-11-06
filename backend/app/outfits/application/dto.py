from dataclasses import dataclass
from datetime import date, datetime

from app.outfits.domain.models import OutfitRecommendation, OutfitWeather, WeeklyWardrobe
from app.outfits.domain.preferences import OutfitPreferences
from app.weather.domain.models import Location, SigunguRegion


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
class RecommendationEngine:
    provider: str
    model: str
    prompt_version: str
    fallback_used: bool = False
    fallback_reason: str | None = None


@dataclass(frozen=True)
class GeneratedOutfits:
    recommendations: tuple[OutfitRecommendation, ...]
    engine: RecommendationEngine


@dataclass(frozen=True)
class TodayOutfitResult:
    forecast: OutfitForecast
    recommendation: OutfitRecommendation
    engine: RecommendationEngine
    generated_at: datetime | None = None
    base_version: str | None = None


@dataclass(frozen=True)
class WeeklyOutfitResult:
    forecast: OutfitForecast
    daily: tuple[OutfitRecommendation, ...]
    wardrobe: WeeklyWardrobe
    summary: str
    engine: RecommendationEngine
    generated_at: datetime | None = None
    base_version: str | None = None


@dataclass(frozen=True)
class NeighborhoodResult:
    location: Location
    result: TodayOutfitResult | WeeklyOutfitResult
    preferences: OutfitPreferences
    adjustments: tuple[str, ...]
    personalization: "PersonalizedOutfits | None" = None
    personalization_cache_hit: bool = False
    region: SigunguRegion | None = None


@dataclass(frozen=True)
class PersonalizedOutfits:
    generated: GeneratedOutfits
    generated_at: datetime
    version: str
    base_version: str
