"""추천 온도 기준과 주간 의류 목록 구성."""

from app.outfits.domain.models import (
    OutfitRecommendation, OutfitWeather, TemperatureBasis, WeeklyWardrobe,
)

def temperature_reference(weather: OutfitWeather) -> tuple[TemperatureBasis, float]:
    """모델에 전달할 온도 기준을 원본 예보에서 선택"""
    if weather.apparent_temperature_min_c is not None and weather.apparent_temperature_max_c is not None:
        return TemperatureBasis.APPARENT, weather.apparent_temperature_max_c
    return TemperatureBasis.ACTUAL, weather.temperature_max_c


def build_weekly_wardrobe(recommendations: tuple[OutfitRecommendation, ...]) -> WeeklyWardrobe:
    """날짜별 추천에서 중복 없는 주간 준비 의류 구성"""
    looks = tuple(recommendation.best for recommendation in recommendations)
    return WeeklyWardrobe(
        tops=tuple(dict.fromkeys(look.top for look in looks if look.top is not None)),
        bottoms=tuple(dict.fromkeys(look.bottom for look in looks if look.bottom is not None)),
        outerwear=tuple(dict.fromkeys(look.outerwear for look in looks if look.outerwear is not None)),
        shoes=tuple(dict.fromkeys(look.shoes for look in looks)),
        accessories=tuple(dict.fromkeys(item for look in looks for item in look.accessories)),
        one_pieces=tuple(dict.fromkeys(look.one_piece for look in looks if look.one_piece is not None)),
    )
