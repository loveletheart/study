# 표준 라이브러리
from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

# 프로젝트 모듈
from app.outfits.domain.models import OutfitRecommendation, OutfitWeather, WeeklyWardrobe, OutfitPreferences
from app.weather.domain.models import Location, SigunguRegion


# 날씨와 추천 엔진 전달 객체
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


# 오늘·주간 추천 결과
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


# 지역별 결과 타입: 오늘·주간 결과 클래스 정의 후 선언
RegionResultT = TypeVar("RegionResultT", TodayOutfitResult, WeeklyOutfitResult)


# 지역별 추천과 개인화 결과
@dataclass(frozen=True)
class RegionOutfitResult(Generic[RegionResultT]):
    location: Location
    result: RegionResultT
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
