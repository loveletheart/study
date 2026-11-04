"""외부 API와 무관한 옷차림 판단 정보."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite


class TemperatureBasis(str, Enum):
    """추천에 사용한 온도 종류."""

    APPARENT = "apparent_temperature"
    ACTUAL = "temperature"


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
    top: str
    bottom: str
    outerwear: str | None
    shoes: str
    accessories: tuple[str, ...] = ()


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
