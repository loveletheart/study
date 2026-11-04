from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class AttributeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CoordinatesResponse(AttributeModel):
    latitude: float
    longitude: float


class LocationResponse(CoordinatesResponse):
    id: int
    name: str
    country_code: str
    country: str | None
    admin1: str | None
    admin2: str | None
    timezone: str | None


class LocationsResponse(AttributeModel):
    locations: list[LocationResponse]
    attribution: str


class CurrentWeatherResponse(AttributeModel):
    time: datetime
    temperature_c: float
    apparent_temperature_c: float | None
    humidity_percent: float | None
    precipitation_mm: float | None
    wind_speed_m_s: float | None
    weather_code: int
    description: str
    is_day: bool


class DailyForecastResponse(AttributeModel):
    date: date
    temperature_min_c: float
    temperature_max_c: float
    temperature_range_c: float
    apparent_temperature_min_c: float | None
    apparent_temperature_max_c: float | None
    precipitation_probability_max_percent: float | None
    precipitation_sum_mm: float | None
    snowfall_sum_cm: float | None
    wind_speed_max_m_s: float | None
    uv_index_max: float | None
    weather_code: int
    description: str


class HourlyForecastResponse(AttributeModel):
    time: datetime
    temperature_c: float
    apparent_temperature_c: float | None
    precipitation_probability_percent: float | None
    wind_speed_m_s: float | None
    weather_code: int
    description: str


class WeatherUnits(BaseModel):
    temperature: str = "°C"
    wind_speed: str = "m/s"
    precipitation: str = "mm"
    snowfall: str = "cm"
    probability: str = "%"


class ForecastMetadata(BaseModel):
    coordinates: CoordinatesResponse
    timezone: str
    fetched_at: datetime = Field(description="우리 서버가 데이터를 가져온 시각. 예보 발표 시각과 다릅니다.")
    provider: str
    source_url: str
    units: WeatherUnits = Field(default_factory=WeatherUnits)


class TodayWeatherResponse(ForecastMetadata):
    current: CurrentWeatherResponse = Field(description="기상 모델 기반 현재 날씨")
    today: DailyForecastResponse
    hourly: list[HourlyForecastResponse]
    summary: str


class WeeklyWeatherResponse(ForecastMetadata):
    daily: list[DailyForecastResponse] = Field(min_length=7, max_length=7)


class WeatherErrorResponse(BaseModel):
    detail: str
