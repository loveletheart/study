"""지역별 공통 추천과 요청별 개인화를 조합한다."""

from dataclasses import replace

from app.outfits.application.dto import NeighborhoodResult
from app.outfits.application.ports import PersonalizedOutfitCache, RegionalOutfitCache
from app.outfits.domain.preferences import OutfitPreferences
from app.outfits.domain.rules import build_weekly_wardrobe
from app.weather.application.ports import LocationCatalog, SigunguResolver


class NeighborhoodOutfitService:
    def __init__(
        self, locations: LocationCatalog, cache: RegionalOutfitCache,
        personalized: PersonalizedOutfitCache, regions: SigunguResolver,
    ) -> None:
        """신뢰한 지역 대표 좌표와 공통 결과 저장소 연결"""
        self._locations = locations
        self._cache = cache
        self._personalized = personalized
        self._regions = regions

    def get_today(self, location_id: int, preferences: OutfitPreferences) -> NeighborhoodResult:
        """동네 기본 추천을 공유하고 개인화한 복사본만 반환"""
        location = self._locations.get(location_id)
        region = self._regions.resolve(location)
        base = self._cache.get_region_today(int(region.code), region.latitude, region.longitude)
        if preferences == OutfitPreferences():
            return NeighborhoodResult(location, base, preferences, (), region=region)
        generated, cache_hit = self._personalized.get(int(region.code), "today", base, preferences)
        recommendation = generated.generated.recommendations[0]
        return NeighborhoodResult(
            location, replace(base, recommendation=recommendation), preferences, recommendation.reasons, generated, cache_hit, region,
        )

    def get_weekly(self, location_id: int, preferences: OutfitPreferences) -> NeighborhoodResult:
        """주간 추천에 개인 조건을 적용하고 준비 의류도 함께 다시 구성"""
        location = self._locations.get(location_id)
        region = self._regions.resolve(location)
        if preferences != OutfitPreferences():
            self._personalized.register(int(region.code), "weekly", preferences)
        base = self._cache.get_region_weekly(int(region.code), region.latitude, region.longitude)
        if preferences == OutfitPreferences():
            return NeighborhoodResult(location, base, preferences, (), region=region)
        generated, cache_hit = self._personalized.get(int(region.code), "weekly", base, preferences)
        daily = generated.generated.recommendations
        adjustments = tuple(dict.fromkeys(reason for recommendation in daily for reason in recommendation.reasons))
        result = replace(base, daily=daily, wardrobe=build_weekly_wardrobe(daily))
        return NeighborhoodResult(location, result, preferences, adjustments, generated, cache_hit, region)
