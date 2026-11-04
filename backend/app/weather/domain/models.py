"""기상 API와 웹 프레임워크에 의존하지 않는 날씨 데이터와 요약 규칙."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite

KST = timezone(timedelta(hours=9), name="Asia/Seoul")

WEATHER_DESCRIPTIONS = {
    0: "맑음", 1: "대체로 맑음", 2: "구름 조금", 3: "흐림",
    45: "안개", 48: "착빙 안개", 51: "약한 이슬비", 53: "이슬비", 55: "강한 이슬비",
    56: "약한 어는 이슬비", 57: "강한 어는 이슬비",
    61: "약한 비", 63: "비", 65: "강한 비", 66: "약한 어는 비", 67: "강한 어는 비",
    71: "약한 눈", 73: "눈", 75: "강한 눈", 77: "싸락눈",
    80: "약한 소나기", 81: "소나기", 82: "강한 소나기",
    85: "약한 소낙눈", 86: "강한 소낙눈", 95: "뇌우", 96: "우박을 동반한 뇌우", 99: "강한 우박을 동반한 뇌우",
}


@dataclass(frozen=True)
class Coordinates:
    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        """위도·경도 범위 검증"""
        if not isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("위도는 -90~90 범위여야 합니다.")
        if not isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("경도는 -180~180 범위여야 합니다.")


@dataclass(frozen=True)
class Location:
    id: int
    name: str
    latitude: float
    longitude: float
    country_code: str
    country: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    timezone: str | None = None


class WeatherDescription:
    weather_code: int

    @property
    def description(self) -> str:
        """날씨 코드를 한글 설명으로 변환"""
        return WEATHER_DESCRIPTIONS.get(self.weather_code, "알 수 없는 날씨")


@dataclass(frozen=True)
class CurrentWeather(WeatherDescription):
    time: datetime
    temperature_c: float
    apparent_temperature_c: float | None
    humidity_percent: float | None
    precipitation_mm: float | None
    wind_speed_m_s: float | None
    weather_code: int
    is_day: bool


@dataclass(frozen=True)
class DailyForecast(WeatherDescription):
    date: date
    temperature_min_c: float
    temperature_max_c: float
    apparent_temperature_min_c: float | None
    apparent_temperature_max_c: float | None
    precipitation_probability_max_percent: float | None
    precipitation_sum_mm: float | None
    snowfall_sum_cm: float | None
    wind_speed_max_m_s: float | None
    uv_index_max: float | None
    weather_code: int

    @property
    def temperature_range_c(self) -> float:
        """최고·최저기온으로 일교차 계산"""
        return round(self.temperature_max_c - self.temperature_min_c, 1)

    def summarize(self) -> str:
        """오늘 예보를 한글 문장으로 요약"""
        summary = (
            f"{self.description}, 최저 {self.temperature_min_c:g}℃, "
            f"최고 {self.temperature_max_c:g}℃가 예상됩니다."
        )
        if self.precipitation_probability_max_percent is not None:
            summary += f" 하루 중 최대 강수확률은 {self.precipitation_probability_max_percent:g}%입니다."
        return summary


@dataclass(frozen=True)
class HourlyForecast(WeatherDescription):
    time: datetime
    temperature_c: float
    apparent_temperature_c: float | None
    precipitation_probability_percent: float | None
    wind_speed_m_s: float | None
    weather_code: int


@dataclass(frozen=True)
class WeatherForecast:
    coordinates: Coordinates
    current: CurrentWeather
    daily: tuple[DailyForecast, ...]
    hourly: tuple[HourlyForecast, ...]
    fetched_at: datetime
    timezone: str = "Asia/Seoul"
    provider: str = "Open-Meteo"
    source_url: str = "https://open-meteo.com/"
