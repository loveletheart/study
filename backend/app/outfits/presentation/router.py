from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.outfits.application.services import OutfitService
from app.outfits.bootstrap import get_outfit_service
from app.outfits.presentation.schemas import TodayOutfitResponse, WeeklyOutfitResponse

router = APIRouter(prefix="/outfits", tags=["outfits"], responses=error_responses(
    ErrorCode.OUTFIT_INVALID_FORECAST,
    ErrorCode.OUTFIT_LLM_NOT_CONFIGURED,
    ErrorCode.OUTFIT_LLM_UNAVAILABLE,
    ErrorCode.OUTFIT_LLM_MODEL_NOT_FOUND,
    ErrorCode.OUTFIT_LLM_TIMEOUT,
    ErrorCode.OUTFIT_LLM_INVALID_RESPONSE,
    ErrorCode.OUTFIT_CLOUD_NOT_CONFIGURED,
    ErrorCode.OUTFIT_CLOUD_UNAVAILABLE,
    ErrorCode.OUTFIT_CLOUD_AUTH_ERROR,
    ErrorCode.OUTFIT_CLOUD_RATE_LIMITED,
    ErrorCode.OUTFIT_CLOUD_TIMEOUT,
    ErrorCode.OUTFIT_CLOUD_INVALID_RESPONSE,
    ErrorCode.WEATHER_INVALID_QUERY,
    ErrorCode.WEATHER_INVALID_RESPONSE,
    ErrorCode.WEATHER_UNAVAILABLE,
    ErrorCode.WEATHER_RATE_LIMITED,
    ErrorCode.WEATHER_TIMEOUT,
))
OutfitServiceDependency = Annotated[OutfitService, Depends(get_outfit_service)]
Latitude = Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False, description="지역 검색 결과의 위도", examples=[37.5665])]
Longitude = Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False, description="지역 검색 결과의 경도", examples=[126.978])]


@router.get(
    "/today", response_model=ApiResponse[TodayOutfitResponse],
    summary="오늘 옷차림 추천", operation_id="get_today_outfit",
    description="오늘 예보로 베스트·워스트 옷차림과 이유를 생성합니다. 자동 전환 설정 시 로컬 실패 후 OpenAI를 사용합니다.",
    response_description="오늘 옷차림, 판단에 사용한 날씨와 준비물",
)
def get_today(latitude: Latitude, longitude: Longitude, service: OutfitServiceDependency) -> ApiResponse[TodayOutfitResponse]:
    """오늘의 베스트·워스트 옷차림 조회"""
    result = service.get_today(latitude, longitude)
    return ApiResponse(data=TodayOutfitResponse.from_result(result))


@router.get(
    "/weekly", response_model=ApiResponse[WeeklyOutfitResponse],
    summary="7일 옷차림 추천", operation_id="get_weekly_outfits",
    description="7일 예보를 한 번에 전달해 날짜별 옷차림과 준비 의류를 생성합니다. 자동 전환 설정 시 로컬 실패 후 OpenAI를 사용합니다.",
    response_description="7일 추천, 주간 준비 의류와 기온 요약",
)
def get_weekly(latitude: Latitude, longitude: Longitude, service: OutfitServiceDependency) -> ApiResponse[WeeklyOutfitResponse]:
    """7일 옷차림과 공통 준비 의류 조회"""
    result = service.get_weekly(latitude, longitude)
    return ApiResponse(data=WeeklyOutfitResponse.from_result(result))
