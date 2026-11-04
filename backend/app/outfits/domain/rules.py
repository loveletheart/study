"""기온 구간과 강수·바람 정보를 이용하는 초기 추천 규칙."""

from dataclasses import dataclass, replace

from app.outfits.domain.models import (
    OutfitLook, OutfitRecommendation, OutfitWeather, TemperatureBasis, WeeklyWardrobe,
)

RAIN_PROBABILITY = 60
WIND_SPEED = 8
TEMPERATURE_RANGE = 10
UV_INDEX = 6
RAIN_CODES = frozenset({51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99})
SNOW_CODES = frozenset({71, 73, 75, 77, 85, 86})


@dataclass(frozen=True)
class TemperatureBand:
    minimum: float
    label: str
    look: OutfitLook


BANDS = (
    TemperatureBand(28, "더운 날씨", OutfitLook("통풍이 좋은 반팔", "가벼운 반바지", None, "통풍 운동화")),
    TemperatureBand(23, "따뜻한 날씨", OutfitLook("반팔", "얇은 긴바지", None, "가벼운 운동화")),
    TemperatureBand(20, "선선한 날씨", OutfitLook("얇은 긴팔", "면바지", "얇은 가디건", "운동화")),
    TemperatureBand(17, "서늘한 날씨", OutfitLook("긴팔", "긴바지", "가디건", "운동화")),
    TemperatureBand(12, "쌀쌀한 날씨", OutfitLook("니트", "긴바지", "재킷", "운동화")),
    TemperatureBand(9, "추운 날씨", OutfitLook("도톰한 니트", "도톰한 긴바지", "코트", "운동화")),
    TemperatureBand(5, "매우 추운 날씨", OutfitLook("보온 이너와 니트", "기모 바지", "두꺼운 코트", "보온 신발")),
    TemperatureBand(float("-inf"), "한겨울 날씨", OutfitLook("보온 이너와 니트", "기모 바지", "패딩", "보온 신발", ("장갑", "목도리"))),
)


def _band(temperature: float) -> TemperatureBand:
    """기준 온도에 해당하는 옷차림 구간 선택"""
    return next(band for band in BANDS if temperature >= band.minimum)


def recommend_outfit(weather: OutfitWeather) -> OutfitRecommendation:
    """하루 날씨로 추천·비추천 옷차림과 이유 구성"""
    low, high = weather.apparent_temperature_min_c, weather.apparent_temperature_max_c
    basis = TemperatureBasis.APPARENT
    if low is None or high is None:
        low, high = weather.temperature_min_c, weather.temperature_max_c
        basis = TemperatureBasis.ACTUAL
    daytime, morning = _band(high), _band(low)
    best = daytime.look
    warm_day = high >= 23
    worst = BANDS[-1].look if warm_day else BANDS[0].look
    label = "체감온도" if basis is TemperatureBasis.APPARENT else "기온"
    reasons = [f"예상 최고 {label} {high:g}℃에 맞춰 {daytime.label}의 기본 구성을 선택했습니다."]
    avoid_reasons = [
        "두꺼운 보온 의류는 낮 기온에 비해 더울 수 있습니다." if warm_day
        else "반팔·반바지만 입으면 아침·저녁에 추울 수 있습니다.",
    ]
    precautions = []
    accessories = list(best.accessories)
    if basis is TemperatureBasis.ACTUAL:
        reasons.append("최저·최고 체감온도가 모두 제공되지 않아 실제 기온을 사용했습니다.")
    actual_range = weather.temperature_max_c - weather.temperature_min_c
    if morning != daytime or actual_range >= TEMPERATURE_RANGE:
        best = replace(best, outerwear=morning.look.outerwear or "얇은 가디건")
        accessories.extend(morning.look.accessories)
        reasons.append(f"예상 최저 {label}는 {low:g}℃이므로 아침·저녁용 겉옷을 함께 구성했습니다.")
        precautions.append(f"일교차는 {actual_range:g}℃입니다. 낮에는 겉옷을 벗어 온도에 맞춰 조절하세요.")
    snow = weather.weather_code in SNOW_CODES or (weather.snowfall_cm is not None and weather.snowfall_cm > 0)
    rain = (
        weather.weather_code in RAIN_CODES
        or (weather.precipitation_mm is not None and weather.precipitation_mm > 0)
        or (weather.precipitation_probability_percent is not None and weather.precipitation_probability_percent >= RAIN_PROBABILITY)
    )
    if snow:
        best = replace(best, shoes="미끄럼 방지 방수 신발")
        worst = replace(worst, shoes="밑창이 매끄러운 신발")
        accessories.append("우산")
        reasons.append("눈 예보가 있어 방수와 미끄럼 방지를 고려했습니다.")
        avoid_reasons.append("밑창이 매끄러운 신발은 눈길에서 미끄러질 수 있습니다.")
        precautions.append("눈·노면 결빙 가능성을 확인하고 이동하세요.")
    elif rain:
        best = replace(best, shoes="미끄럼 방지 생활방수 신발")
        worst = replace(worst, shoes="물이 잘 스며드는 캔버스 신발")
        accessories.append("우산")
        reasons.append("강수 예보가 있어 우산과 생활방수 신발을 포함했습니다.")
        avoid_reasons.append("물이 잘 스며드는 신발은 비에 젖기 쉽습니다.")
        precautions.append("강수확률은 비가 온다는 확정이 아니므로 외출 전 최신 예보를 확인하세요.")
    if weather.wind_speed_m_s is not None and weather.wind_speed_m_s >= WIND_SPEED:
        if best.outerwear is None or best.outerwear in {"얇은 가디건", "가디건"}:
            best = replace(best, outerwear="바람막이" if low >= 17 else "보온 안감 바람막이")
        reasons.append(f"예상 최대 풍속 {weather.wind_speed_m_s:g}m/s를 고려해 바람을 막을 겉옷을 구성했습니다.")
        precautions.append("노출된 장소에서는 겉옷을 여미고, 보행에 지장이 있으면 우산 사용을 피하세요.")
    if weather.uv_index is not None and weather.uv_index >= UV_INDEX:
        accessories.append("모자")
        reasons.append(f"예상 최대 자외선 지수 {weather.uv_index:g}를 고려해 모자를 포함했습니다.")
    if weather.precipitation_probability_percent is None:
        precautions.append("강수확률 정보가 제공되지 않았습니다.")
    if weather.wind_speed_m_s is None:
        precautions.append("풍속 정보가 제공되지 않았습니다.")
    best = replace(best, accessories=tuple(dict.fromkeys(accessories)))
    return OutfitRecommendation(
        date=weather.date, weather=weather, temperature_basis=basis, reference_temperature_c=high,
        best=best, worst=worst, reasons=tuple(reasons), avoid_reasons=tuple(avoid_reasons),
        precautions=tuple(precautions),
    )


def build_weekly_wardrobe(recommendations: tuple[OutfitRecommendation, ...]) -> WeeklyWardrobe:
    """날짜별 추천에서 중복 없는 주간 준비 의류 구성"""
    looks = tuple(recommendation.best for recommendation in recommendations)
    return WeeklyWardrobe(
        tops=tuple(dict.fromkeys(look.top for look in looks)),
        bottoms=tuple(dict.fromkeys(look.bottom for look in looks)),
        outerwear=tuple(dict.fromkeys(look.outerwear for look in looks if look.outerwear is not None)),
        shoes=tuple(dict.fromkeys(look.shoes for look in looks)),
        accessories=tuple(dict.fromkeys(item for look in looks for item in look.accessories)),
    )
