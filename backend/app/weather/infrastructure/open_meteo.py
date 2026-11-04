"""Open-Meteo의 응답 형식을 도메인 모델로 변환하는 어댑터."""

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from math import isfinite

from app.weather.application.exceptions import WeatherProviderDataError
from app.weather.domain.models import (
    KST, Coordinates, CurrentWeather, DailyForecast, HourlyForecast, Location, WeatherForecast,
)
from app.weather.infrastructure.cache import TTLCache
from app.weather.infrastructure.http_client import JsonHttpClient

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

CURRENT_FIELDS = {
    "temperature_2m": "°C", "apparent_temperature": "°C",
    "relative_humidity_2m": "%", "precipitation": "mm",
    "wind_speed_10m": "m/s", "weather_code": "wmo code", "is_day": "",
}
DAILY_FIELDS = {
    "temperature_2m_min": "°C", "temperature_2m_max": "°C",
    "apparent_temperature_min": "°C", "apparent_temperature_max": "°C",
    "precipitation_probability_max": "%", "precipitation_sum": "mm",
    "snowfall_sum": "cm", "wind_speed_10m_max": "m/s",
    "uv_index_max": "", "weather_code": "wmo code",
}
HOURLY_FIELDS = {
    "temperature_2m": "°C", "apparent_temperature": "°C",
    "precipitation_probability": "%", "wind_speed_10m": "m/s", "weather_code": "wmo code",
}


# 필수 숫자 검증: None이면 오류
def _number(value: object, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("Invalid numeric weather value")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError("Weather value is out of bounds")
    return float(value)


# 선택 숫자 검증: None이면 정보 없음 유지
def _optional_number(value: object, *, minimum: float | None = None, maximum: float | None = None) -> float | None:
    if value is None:
        return None
    return _number(value, minimum=minimum, maximum=maximum)


# 정수 형식과 최솟값 검증
def _integer(value, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError("Invalid integer weather value")
    return value


# 제공사 시각을 한국 시간으로 변환
def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("Expected local ISO time")
    return parsed.replace(tzinfo=KST)


# 날씨 데이터 단위 검증
def _validate_units(payload: dict, section: str, expected: dict) -> None:
    units = payload[f"{section}_units"]
    for field, unit in expected.items():
        if units[field] != unit:
            raise ValueError(f"Unexpected unit for {section}.{field}")


# 예보 배열 길이 검증
def _arrays(section: dict, fields: dict, length: int) -> None:
    for field in ("time", *fields):
        if not isinstance(section[field], list) or len(section[field]) != length:
            raise ValueError(f"Incomplete array: {field}")


class OpenMeteoProvider:
    # HTTP 클라이언트와 캐시 주입
    def __init__(
        self,
        http: JsonHttpClient,
        cache: TTLCache,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._http = http
        self._cache = cache
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # 캐시를 이용해 지역 검색
    def search_locations(self, query: str, limit: int) -> tuple[Location, ...]:
        return self._cache.get_or_load(
            ("locations", query.casefold(), limit), lambda: self._load_locations(query, limit)
        )

    # 지역 API 호출 후 위치 정보 변환
    def _load_locations(self, query: str, limit: int) -> tuple[Location, ...]:
        payload = self._http.get(GEOCODING_URL, {
            "name": query, "count": limit, "language": "ko", "format": "json", "countryCode": "KR",
        })
        try:
            rows = payload.get("results", [])
            if not isinstance(rows, list):
                raise ValueError("Invalid geocoding results")
            locations = []
            for row in rows:
                if row["country_code"] != "KR":
                    continue
                latitude = _number(row["latitude"], minimum=-90, maximum=90)
                longitude = _number(row["longitude"], minimum=-180, maximum=180)
                if not isinstance(row["name"], str) or not row["name"].strip():
                    raise ValueError("Missing location name")
                optional_text = {}
                for field in ("country", "admin1", "admin2", "timezone"):
                    value = row.get(field)
                    if value is not None and not isinstance(value, str):
                        raise ValueError("Invalid location text")
                    optional_text[field] = value
                locations.append(Location(
                    id=_integer(row["id"], minimum=1), name=row["name"],
                    latitude=latitude, longitude=longitude, country_code="KR", **optional_text,
                ))
            return tuple(locations[:limit])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise WeatherProviderDataError() from exc

    # 좌표·날짜별 예보 캐시 조회
    def get_forecast(self, coordinates: Coordinates) -> WeatherForecast:
        # 날짜도 캐시 키에 포함해 한국 시간 자정 이후 어제 예보를 반환하지 않는다.
        today = self._clock().astimezone(KST).date()
        return self._cache.get_or_load(
            ("forecast", coordinates.latitude, coordinates.longitude, today),
            lambda: self._load_forecast(coordinates),
        )

    # 예보 API 호출 및 응답 검증
    def _load_forecast(self, coordinates: Coordinates) -> WeatherForecast:
        payload = self._http.get(FORECAST_URL, {
            "latitude": coordinates.latitude, "longitude": coordinates.longitude,
            "timezone": "Asia/Seoul", "forecast_days": 7,
            "temperature_unit": "celsius", "wind_speed_unit": "ms", "precipitation_unit": "mm",
            "current": ",".join(CURRENT_FIELDS), "daily": ",".join(DAILY_FIELDS),
            "hourly": ",".join(HOURLY_FIELDS),
        })
        fetched_at = self._clock()
        try:
            if payload["timezone"] != "Asia/Seoul" or payload["utc_offset_seconds"] != 32400:
                raise ValueError("Unexpected timezone")
            for section, fields in (("current", CURRENT_FIELDS), ("daily", DAILY_FIELDS), ("hourly", HOURLY_FIELDS)):
                _validate_units(payload, section, fields)
            day_data, hour_data, current = payload["daily"], payload["hourly"], payload["current"]
            _arrays(day_data, DAILY_FIELDS, 7)
            _arrays(hour_data, HOURLY_FIELDS, 168)
            first_date = fetched_at.astimezone(KST).date()
            days = tuple(self._parse_day(day_data, i) for i in range(7))
            if tuple(day.date for day in days) != tuple(first_date + timedelta(days=i) for i in range(7)):
                raise ValueError("Forecast dates must start today and be consecutive")
            hours = tuple(self._parse_hour(hour_data, i) for i in range(168))
            first_hour = datetime.combine(first_date, datetime.min.time(), tzinfo=KST)
            if tuple(hour.time for hour in hours) != tuple(first_hour + timedelta(hours=i) for i in range(168)):
                raise ValueError("Hourly timestamps must cover the full seven days")
            current_time = _time(current["time"])
            if current_time.date() != first_date or type(current["is_day"]) is not int or current["is_day"] not in (0, 1):
                raise ValueError("Invalid current weather time or day flag")
            current_weather = CurrentWeather(
                time=current_time,
                temperature_c=_number(current["temperature_2m"]),
                apparent_temperature_c=_optional_number(current["apparent_temperature"]),
                humidity_percent=_optional_number(current["relative_humidity_2m"], minimum=0, maximum=100),
                precipitation_mm=_optional_number(current["precipitation"], minimum=0),
                wind_speed_m_s=_optional_number(current["wind_speed_10m"], minimum=0),
                weather_code=_integer(current["weather_code"]), is_day=bool(current["is_day"]),
            )
            return WeatherForecast(coordinates, current_weather, days, hours, fetched_at)
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
            raise WeatherProviderDataError() from exc

    # 일별 데이터를 날씨 객체로 변환
    @staticmethod
    def _parse_day(data: dict, i: int) -> DailyForecast:
        minimum = _number(data["temperature_2m_min"][i])
        maximum = _number(data["temperature_2m_max"][i])
        if minimum > maximum:
            raise ValueError("Minimum temperature exceeds maximum")
        return DailyForecast(
            date=date.fromisoformat(data["time"][i]),
            temperature_min_c=minimum, temperature_max_c=maximum,
            apparent_temperature_min_c=_optional_number(data["apparent_temperature_min"][i]),
            apparent_temperature_max_c=_optional_number(data["apparent_temperature_max"][i]),
            precipitation_probability_max_percent=_optional_number(data["precipitation_probability_max"][i], minimum=0, maximum=100),
            precipitation_sum_mm=_optional_number(data["precipitation_sum"][i], minimum=0),
            snowfall_sum_cm=_optional_number(data["snowfall_sum"][i], minimum=0),
            wind_speed_max_m_s=_optional_number(data["wind_speed_10m_max"][i], minimum=0),
            uv_index_max=_optional_number(data["uv_index_max"][i], minimum=0),
            weather_code=_integer(data["weather_code"][i]),
        )

    # 시간별 데이터를 날씨 객체로 변환
    @staticmethod
    def _parse_hour(data: dict, i: int) -> HourlyForecast:
        return HourlyForecast(
            time=_time(data["time"][i]), temperature_c=_number(data["temperature_2m"][i]),
            apparent_temperature_c=_optional_number(data["apparent_temperature"][i]),
            precipitation_probability_percent=_optional_number(data["precipitation_probability"][i], minimum=0, maximum=100),
            wind_speed_m_s=_optional_number(data["wind_speed_10m"][i], minimum=0),
            weather_code=_integer(data["weather_code"][i]),
        )
