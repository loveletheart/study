"""외부 API와 무관한 옷차림 판단 정보."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite


class TemperatureBasis(str, Enum):
    """추천에 사용한 온도 종류."""

    APPARENT = "apparent_temperature"
    ACTUAL = "temperature"


class OutfitType(str, Enum):
    SEPARATES = "separates"
    ONE_PIECE = "one_piece"


def validate_clothing_name(value: str) -> str:
    """빈값을 가장한 문자열을 의류명으로 저장하지 않는다."""
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("Invalid clothing name")
    if value.strip().casefold() in {"null", "none", "nil", "undefined", "n/a", "na", "없음", "해당없음", "해당 없음", "-"}:
        raise ValueError("Use JSON null for missing clothing, not placeholder text")
    return value


def validate_outfit_parts(outfit_type: OutfitType, top: str | None, bottom: str | None, one_piece: str | None) -> None:
    """원피스와 상하의 조합의 필수/빈값 조건을 검증한다."""
    if outfit_type == OutfitType.ONE_PIECE:
        if one_piece is None or top is not None or bottom is not None:
            raise ValueError("One-piece outfits require one_piece and null top/bottom")
    elif outfit_type == OutfitType.SEPARATES:
        if top is None or bottom is None or one_piece is not None:
            raise ValueError("Separate outfits require top/bottom and null one_piece")
    else:
        raise ValueError("Unknown outfit type")


@dataclass(frozen=True)
class OutfitWeather:
    date: date
    temperature_min_c: float
    temperature_max_c: float
    apparent_temperature_min_c: float | None
    apparent_temperature_max_c: float | None
    precipitation_probability_percent: float | None
    precipitation_mm: float | None
    snowfall_cm: float | None
    wind_speed_m_s: float | None
    uv_index: float | None
    weather_code: int
    description: str

    def __post_init__(self) -> None:
        """추천에 필요한 기온과 선택 값의 범위 검증"""
        values = (self.temperature_min_c, self.temperature_max_c)
        if any(isinstance(value, bool) or not isfinite(value) for value in values):
            raise ValueError("Invalid temperature")
        if self.temperature_min_c > self.temperature_max_c:
            raise ValueError("Reversed temperature range")
        optional = (
            self.apparent_temperature_min_c, self.apparent_temperature_max_c,
            self.precipitation_probability_percent, self.precipitation_mm,
            self.snowfall_cm, self.wind_speed_m_s, self.uv_index,
        )
        if any(value is not None and (isinstance(value, bool) or not isfinite(value)) for value in optional):
            raise ValueError("Invalid optional weather value")
        low, high = self.apparent_temperature_min_c, self.apparent_temperature_max_c
        if low is not None and high is not None and low > high:
            raise ValueError("Reversed apparent temperature range")
        probability = self.precipitation_probability_percent
        if probability is not None and not 0 <= probability <= 100:
            raise ValueError("Invalid precipitation probability")
        if any(value is not None and value < 0 for value in optional[3:]):
            raise ValueError("Negative weather metric")


@dataclass(frozen=True)
class OutfitLook:
    top: str | None
    bottom: str | None
    outerwear: str | None
    shoes: str
    accessories: tuple[str, ...] = ()
    outfit_type: OutfitType = OutfitType.SEPARATES
    one_piece: str | None = None

    def __post_init__(self) -> None:
        validate_outfit_parts(self.outfit_type, self.top, self.bottom, self.one_piece)
        for value in (self.top, self.bottom, self.one_piece, self.outerwear):
            if value is not None:
                validate_clothing_name(value)
        validate_clothing_name(self.shoes)
        for value in self.accessories:
            validate_clothing_name(value)


@dataclass(frozen=True)
class OutfitRecommendation:
    date: date
    weather: OutfitWeather
    temperature_basis: TemperatureBasis
    reference_temperature_c: float
    best: OutfitLook
    worst: OutfitLook
    reasons: tuple[str, ...]
    avoid_reasons: tuple[str, ...]
    precautions: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyWardrobe:
    tops: tuple[str, ...]
    bottoms: tuple[str, ...]
    outerwear: tuple[str, ...]
    shoes: tuple[str, ...]
    accessories: tuple[str, ...]
    one_pieces: tuple[str, ...] = ()
