from typing import Protocol

from app.outfits.application.dto import GeneratedOutfits, OutfitForecast, PersonalizedOutfits, TodayOutfitResult, WeeklyOutfitResult
from app.outfits.domain.models import OutfitWeather
from app.outfits.domain.preferences import OutfitPreferences


class OutfitWeatherReader(Protocol):
    def get_forecast(self, latitude: float, longitude: float) -> OutfitForecast:
        """옷차림 판단에 필요한 7일 예보 조회 계약"""
        ...


class OutfitRecommender(Protocol):
    def recommend(self, days: tuple[OutfitWeather, ...]) -> GeneratedOutfits:
        """날짜별 날씨에 맞는 옷차림 생성 계약"""
        ...


class RegionalOutfitCache(Protocol):
    def get_region_today(self, location_id: int, latitude: float, longitude: float) -> TodayOutfitResult:
        """지역별 공통 오늘 추천 조회"""
        ...

    def get_region_weekly(self, location_id: int, latitude: float, longitude: float) -> WeeklyOutfitResult:
        """지역별 공통 주간 추천 조회"""
        ...


class OutfitPersonalizer(Protocol):
    def personalize(self, base: GeneratedOutfits, preferences: OutfitPreferences) -> GeneratedOutfits:
        """공통 추천과 개인 조건에 맞는 의류·이유를 동적으로 생성"""
        ...


class PersonalizedOutfitCache(Protocol):
    def get(
        self, location_id: int, kind: str, base: TodayOutfitResult | WeeklyOutfitResult,
        preferences: OutfitPreferences,
    ) -> tuple[PersonalizedOutfits, bool]:
        """기본 버전·조건 조합별 개인 생성 결과와 캐시 사용 여부 조회"""
        ...
