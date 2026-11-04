"""동기 외부 HTTP 호출은 FastAPI의 동기 경로 실행 스레드에서 처리한다."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.weather.application.exceptions import (
    InvalidWeatherQueryError, WeatherError,
    WeatherProviderTimeoutError, WeatherProviderUnavailableError, WeatherRateLimitError,
)
from app.weather.application.services import WeatherService
from app.weather.bootstrap import get_weather_service
from app.weather.presentation.schemas import (
    CoordinatesResponse, CurrentWeatherResponse, DailyForecastResponse, HourlyForecastResponse,
    LocationsResponse, TodayWeatherResponse, WeatherErrorResponse, WeeklyWeatherResponse,
)

router = APIRouter(prefix="/weather", tags=["weather"], responses={
    502: {"model": WeatherErrorResponse, "description": "외부 응답 형식 오류"},
    503: {"model": WeatherErrorResponse, "description": "외부 서비스 연결 실패 또는 요청 한도 초과"},
    504: {"model": WeatherErrorResponse, "description": "외부 서비스 응답 시간 초과"},
})
WeatherServiceDependency = Annotated[WeatherService, Depends(get_weather_service)]
Latitude = Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False, description="선택한 지역의 위도")]
Longitude = Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False, description="선택한 지역의 경도")]


def _http_error(exc: WeatherError) -> HTTPException:
    if isinstance(exc, InvalidWeatherQueryError):
        status_code = 422
    elif isinstance(exc, WeatherProviderTimeoutError):
        status_code = 504
    elif isinstance(exc, (WeatherProviderUnavailableError, WeatherRateLimitError)):
        status_code = 503
    else:
        status_code = 502
    return HTTPException(status_code=status_code, detail=str(exc))


@router.get("/locations", response_model=LocationsResponse)
def search_locations(
    query: Annotated[str, Query(min_length=2, max_length=100, description="국내 지역명. 예: 서울, 부산")],
    service: WeatherServiceDependency,
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> LocationsResponse:
    try:
        return LocationsResponse.model_validate(service.search_locations(query, limit))
    except WeatherError as exc:
        raise _http_error(exc) from exc


@router.get("/today", response_model=TodayWeatherResponse)
def get_today(latitude: Latitude, longitude: Longitude, service: WeatherServiceDependency) -> TodayWeatherResponse:
    try:
        result = service.get_today(latitude, longitude)
    except WeatherError as exc:
        raise _http_error(exc) from exc
    forecast = result.forecast
    return TodayWeatherResponse(
        coordinates=CoordinatesResponse.model_validate(forecast.coordinates),
        timezone=forecast.timezone, fetched_at=forecast.fetched_at,
        provider=forecast.provider, source_url=forecast.source_url,
        current=CurrentWeatherResponse.model_validate(forecast.current),
        today=DailyForecastResponse.model_validate(result.today),
        hourly=[HourlyForecastResponse.model_validate(hour) for hour in result.hourly],
        summary=result.summary,
    )


@router.get("/weekly", response_model=WeeklyWeatherResponse)
def get_weekly(latitude: Latitude, longitude: Longitude, service: WeatherServiceDependency) -> WeeklyWeatherResponse:
    try:
        forecast = service.get_weekly(latitude, longitude)
    except WeatherError as exc:
        raise _http_error(exc) from exc
    return WeeklyWeatherResponse(
        coordinates=CoordinatesResponse.model_validate(forecast.coordinates),
        timezone=forecast.timezone, fetched_at=forecast.fetched_at,
        provider=forecast.provider, source_url=forecast.source_url,
        daily=[DailyForecastResponse.model_validate(day) for day in forecast.daily],
    )
