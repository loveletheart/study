"""옷차림 날씨·의류 구성·개인 선택 조건의 도메인 모델."""

# 표준 라이브러리
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
        raise ValueError("의류명이 비어 있거나 허용된 형식·길이를 벗어났습니다.")
    if value.strip().casefold() in {"null", "none", "nil", "undefined", "n/a", "na", "없음", "해당없음", "해당 없음", "-"}:
        raise ValueError("의류가 없으면 자리 채우기 문자열 대신 실제 JSON null을 사용해야 합니다.")
    return value


def validate_outfit_parts(outfit_type: OutfitType, top: str | None, bottom: str | None, one_piece: str | None) -> None:
    """원피스와 상하의 조합의 필수/빈값 조건을 검증한다."""
    if outfit_type == OutfitType.ONE_PIECE:
        if one_piece is None or top is not None or bottom is not None:
            raise ValueError("원피스 구성은 one_piece가 필요하며 top과 bottom은 null이어야 합니다.")
    elif outfit_type == OutfitType.SEPARATES:
        if top is None or bottom is None or one_piece is not None:
            raise ValueError("상하의 구성은 top과 bottom이 필요하며 one_piece는 null이어야 합니다.")
    else:
        raise ValueError("지원하지 않는 옷차림 구성 종류입니다.")


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
            raise ValueError("기온 값이 유효한 유한 숫자가 아닙니다.")
        if self.temperature_min_c > self.temperature_max_c:
            raise ValueError("최저기온이 최고기온보다 높습니다.")
        optional = (
            self.apparent_temperature_min_c, self.apparent_temperature_max_c,
            self.precipitation_probability_percent, self.precipitation_mm,
            self.snowfall_cm, self.wind_speed_m_s, self.uv_index,
        )
        if any(value is not None and (isinstance(value, bool) or not isfinite(value)) for value in optional):
            raise ValueError("선택 날씨 값이 유효한 유한 숫자가 아닙니다.")
        low, high = self.apparent_temperature_min_c, self.apparent_temperature_max_c
        if low is not None and high is not None and low > high:
            raise ValueError("최저 체감온도가 최고 체감온도보다 높습니다.")
        probability = self.precipitation_probability_percent
        if probability is not None and not 0 <= probability <= 100:
            raise ValueError("강수확률은 0~100 범위여야 합니다.")
        if any(value is not None and value < 0 for value in optional[3:]):
            raise ValueError("강수량·적설량·풍속·자외선 지수는 음수일 수 없습니다.")


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


class ColdSensitivity(str, Enum):
    NORMAL = "normal"
    COLD = "cold"
    WARM = "warm"


class OutfitStyle(str, Enum):
    DEFAULT = "default"
    CASUAL = "casual"
    FORMAL = "formal"


class Activity(str, Enum):
    DAILY = "daily"
    OUTDOOR = "outdoor"
    ACTIVE = "active"


class ClothingPreference(str, Enum):
    ANY = "any"
    MENSWEAR = "menswear"
    WOMENSWEAR = "womenswear"


class AvoidItem(str, Enum):
    SKIRTS = "skirts"
    DRESSES = "dresses"
    SHORTS = "shorts"
    SANDALS = "sandals"
    HEELS = "heels"
    SLEEVELESS = "sleeveless"


@dataclass(frozen=True)
class OutfitPreferences:
    cold_sensitivity: ColdSensitivity = ColdSensitivity.NORMAL
    style: OutfitStyle = OutfitStyle.DEFAULT
    activity: Activity = Activity.DAILY
    clothing_preference: ClothingPreference = ClothingPreference.ANY
    avoid_items: tuple[AvoidItem, ...] = ()

    def __post_init__(self) -> None:
        """선택 순서와 중복이 달라도 동일한 추천 조건으로 공유한다."""
        object.__setattr__(self, "avoid_items", tuple(sorted({AvoidItem(item) for item in self.avoid_items}, key=lambda item: item.value)))
