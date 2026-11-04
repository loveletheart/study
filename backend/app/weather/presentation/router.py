from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.weather.application.services import WeatherService
from app.weather.bootstrap import get_weather_service
from app.weather.presentation.schemas import (
    LocationsResponse, TodayWeatherResponse, WeeklyWeatherResponse,
)

router = APIRouter(prefix="/weather", tags=["weather"], responses=error_responses(
    ErrorCode.WEATHER_INVALID_QUERY,
    ErrorCode.WEATHER_INVALID_RESPONSE,
    ErrorCode.WEATHER_UNAVAILABLE,
    ErrorCode.WEATHER_RATE_LIMITED,
    ErrorCode.WEATHER_TIMEOUT,
))
WeatherServiceDependency = Annotated[WeatherService, Depends(get_weather_service)]
Latitude = Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False, description="지역 검색 결과의 위도. 서울 예시: 37.5665", examples=[37.5665])]
Longitude = Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False, description="지역 검색 결과의 경도. 서울 예시: 126.978", examples=[126.978])]


"""국내 지역명으로 위치 후보 검색"""
@router.get(
    "/locations", response_model=ApiResponse[LocationsResponse],
    summary="국내 지역 검색", operation_id="search_weather_locations",
    description="국내 지역을 검색하고 선택에 필요한 위도·경도를 반환합니다.",
    response_description="지역 후보 목록과 날씨 조회에 사용할 위도·경도",
)
def search_locations(
    query: Annotated[str, Query(min_length=2, max_length=100, description="2~100자의 국내 지역명", examples=["서울"])],
    service: WeatherServiceDependency,
    limit: Annotated[int, Query(ge=1, le=10, description="검색 결과 최대 개수(1~10)")] = 5,
) -> ApiResponse[LocationsResponse]:
    result = service.search_locations(query, limit)
    return ApiResponse(data=LocationsResponse.model_validate(result))


"""현재 날씨와 오늘 예보 조회"""
@router.get(
    "/today", response_model=ApiResponse[TodayWeatherResponse],
    summary="오늘 날씨 조회", operation_id="get_today_weather",
    description="한국 시간 기준 현재 날씨, 오늘 예보와 24시간 정보를 반환합니다.",
    response_description="모델 기반 현재 날씨, 오늘 일별·24시간 예보와 한글 요약",
)
def get_today(latitude: Latitude, longitude: Longitude, service: WeatherServiceDependency) -> ApiResponse[TodayWeatherResponse]:
    result = service.get_today(latitude, longitude)
    return ApiResponse(data=TodayWeatherResponse.from_result(result))


"""오늘부터 7일 예보 조회"""
@router.get(
    "/weekly", response_model=ApiResponse[WeeklyWeatherResponse],
    summary="오늘부터 7일 예보 조회", operation_id="get_weekly_weather",
    description="선택한 좌표의 오늘부터 7일간 기온·강수·바람 정보를 반환합니다.",
    response_description="한국 시간 기준 오늘부터 연속된 7일의 일별 날씨",
)
def get_weekly(latitude: Latitude, longitude: Longitude, service: WeatherServiceDependency) -> ApiResponse[WeeklyWeatherResponse]:
    result = service.get_weekly(latitude, longitude)
    return ApiResponse(data=WeeklyWeatherResponse.model_validate(result))
