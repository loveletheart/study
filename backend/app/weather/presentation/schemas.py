# 표준 라이브러리
from datetime import date as Date, datetime

# 외부 라이브러리
from pydantic import BaseModel, ConfigDict, Field

# 프로젝트 모듈
from app.weather.application.dto import TodayWeatherResult


class AttributeModel(BaseModel):
    """도메인 객체와 DTO의 속성에서 응답 값을 읽는 공통 모델."""
    model_config = ConfigDict(from_attributes=True)


class CoordinatesResponse(AttributeModel):
    """사용자가 선택한 위치의 WGS84 좌표."""

    latitude: float = Field(description="요청한 위도(-90~90)", examples=[37.5665])
    longitude: float = Field(description="요청한 경도(-180~180)", examples=[126.978])


class LocationResponse(CoordinatesResponse):
    """지역 선택 화면에서 동명 지역을 구분할 검색 후보."""

    id: int = Field(description="GeoNames 지역 식별자")
    name: str = Field(description="지역 이름", examples=["서울"])
    country_code: str = Field(description="국가 코드. 국내 검색에서는 KR")
    country: str | None = Field(description="국가 이름. 미제공 시 null")
    admin1: str | None = Field(description="상위 행정구역 이름. 미제공 시 null")
    admin2: str | None = Field(description="하위 행정구역 이름. 미제공 시 null")
    timezone: str | None = Field(description="검색 후보의 시간대. 미제공 시 null")


class LocationsResponse(AttributeModel):
    """지역 검색 결과. 일치하는 지역이 없으면 빈 목록."""

    locations: list[LocationResponse] = Field(description="검색 조건에 맞는 국내 지역 후보")
    attribution: str = Field(description="지역 데이터 출처. 화면에서 출처 표기에 사용")


class CurrentWeatherResponse(AttributeModel):
    """기상 모델 기반 현재 날씨. 선택 항목의 null은 정보 없음을 뜻한다."""

    time: datetime = Field(description="현재 날씨의 모델 기준 시각(+09:00). 관측소 실측 시각이 아닙니다.")
    temperature_c: float = Field(description="현재 기온(°C)")
    apparent_temperature_c: float | None = Field(description="현재 체감온도(°C)")
    humidity_percent: float | None = Field(description="현재 상대습도(%)")
    precipitation_mm: float | None = Field(description="제공사의 현재 시간 구간 강수량(mm)")
    wind_speed_m_s: float | None = Field(description="지상 10m 풍속(m/s)")
    weather_code: int = Field(description="WMO 날씨 코드")
    description: str = Field(description="날씨 코드의 한글 설명")
    is_day: bool = Field(description="낮이면 true, 밤이면 false")


class DailyForecastResponse(AttributeModel):
    """한국 시간 기준 하루의 예보와 옷차림 판단에 사용할 날씨 정보."""

    date: Date = Field(description="예보 날짜(Asia/Seoul)")
    temperature_min_c: float = Field(description="일 최저기온(°C)")
    temperature_max_c: float = Field(description="일 최고기온(°C)")
    temperature_range_c: float = Field(description="일교차: 최고기온 - 최저기온(°C)")
    apparent_temperature_min_c: float | None = Field(description="일 최저 체감온도(°C)")
    apparent_temperature_max_c: float | None = Field(description="일 최고 체감온도(°C)")
    precipitation_probability_max_percent: float | None = Field(description="하루 중 최대 강수확률(%). 비가 온다는 확정 의미가 아닙니다.")
    precipitation_sum_mm: float | None = Field(description="하루 누적 강수량(mm)")
    snowfall_sum_cm: float | None = Field(description="하루 누적 적설량(cm)")
    wind_speed_max_m_s: float | None = Field(description="하루 최대 풍속(m/s)")
    uv_index_max: float | None = Field(description="하루 최대 자외선 지수")
    weather_code: int = Field(description="그날의 대표 WMO 날씨 코드")
    description: str = Field(description="대표 날씨 코드의 한글 설명")


class HourlyForecastResponse(AttributeModel):
    """아침·낮·저녁 외출 시 비교할 시간별 예보."""

    time: datetime = Field(description="예보 대상 시각(+09:00)")
    temperature_c: float = Field(description="해당 시간의 기온(°C)")
    apparent_temperature_c: float | None = Field(description="해당 시간의 체감온도(°C)")
    precipitation_probability_percent: float | None = Field(description="해당 시간의 강수확률(%)")
    wind_speed_m_s: float | None = Field(description="해당 시간의 풍속(m/s)")
    weather_code: int = Field(description="해당 시간의 WMO 날씨 코드")
    description: str = Field(description="날씨 코드의 한글 설명")


class WeatherUnits(BaseModel):
    """화면에서 수치를 표시할 때 사용할 고정 단위."""

    temperature: str = Field(default="°C", description="기온 단위")
    wind_speed: str = Field(default="m/s", description="풍속 단위")
    precipitation: str = Field(default="mm", description="강수량 단위")
    snowfall: str = Field(default="cm", description="적설량 단위")
    probability: str = Field(default="%", description="확률 단위")


class ForecastMetadata(AttributeModel):
    """오늘·주간 날씨가 공유하는 위치, 시간과 출처 정보."""

    coordinates: CoordinatesResponse = Field(description="요청한 좌표. 실제 예보 격자 중심 좌표와 다를 수 있습니다.")
    timezone: str = Field(description="예보 날짜를 해석하는 시간대. 현재 Asia/Seoul로 고정")
    fetched_at: datetime = Field(description="우리 서버가 데이터를 가져온 시각. 예보 발표 시각과 다릅니다.")
    provider: str = Field(description="날씨 데이터 제공사")
    source_url: str = Field(description="화면 출처 표시에 사용할 제공사 링크")
    units: WeatherUnits = Field(default_factory=WeatherUnits, description="응답 수치의 단위")


class TodayWeatherResponse(ForecastMetadata):
    """오늘 날씨 화면에서 사용할 현재·일별·시간별 정보와 요약."""
    current: CurrentWeatherResponse = Field(description="기상 모델 기반 현재 날씨")
    today: DailyForecastResponse = Field(description="오늘 하루의 예보")
    hourly: list[HourlyForecastResponse] = Field(description="한국 시간 오늘 00시부터 23시까지의 예보")
    summary: str = Field(description="오늘 날씨의 한글 요약. 옷차림 추천은 포함하지 않습니다.")

    @classmethod
    def from_result(cls, result: TodayWeatherResult) -> "TodayWeatherResponse":
        """오늘 조회 결과를 응답으로 변환"""
        forecast = result.forecast
        return cls.model_validate({
            "coordinates": forecast.coordinates,
            "timezone": forecast.timezone,
            "fetched_at": forecast.fetched_at,
            "provider": forecast.provider,
            "source_url": forecast.source_url,
            "current": forecast.current,
            "today": result.today,
            "hourly": result.hourly,
            "summary": result.summary,
        })


class WeeklyWeatherResponse(ForecastMetadata):
    """오늘부터 7일 예보를 날짜순으로 제공하는 응답."""

    daily: list[DailyForecastResponse] = Field(min_length=7, max_length=7, description="오늘 포함 연속된 7일의 예보")
