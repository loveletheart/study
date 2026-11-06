from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.outfits.bootstrap import get_cached_outfit_service
from app.outfits.infrastructure.result_cache import CachedOutfitService
from app.outfits.presentation.schemas import TodayOutfitResponse, WeeklyOutfitResponse

router = APIRouter(prefix="/outfits", tags=["outfits"], responses=error_responses(
    ErrorCode.OUTFIT_INVALID_FORECAST,
    ErrorCode.OUTFIT_WEEKLY_NOT_READY,
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
    ErrorCode.WEATHER_REGION_NOT_CONFIGURED,
    ErrorCode.WEATHER_INVALID_RESPONSE,
    ErrorCode.WEATHER_UNAVAILABLE,
    ErrorCode.WEATHER_RATE_LIMITED,
    ErrorCode.WEATHER_TIMEOUT,
))
OutfitServiceDependency = Annotated[CachedOutfitService, Depends(get_cached_outfit_service)]
Latitude = Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False, description="지역 검색 결과의 위도", examples=[37.5665])]
Longitude = Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False, description="지역 검색 결과의 경도", examples=[126.978])]


@router.get(
    "/today", response_model=ApiResponse[TodayOutfitResponse],
    summary="오늘 옷차림 추천", operation_id="get_today_outfit",
    description="저장된 오늘 추천을 제공하고 조회한 지역은 매시간 갱신합니다. 최초 조회는 생성 시간이 필요합니다. 자동 전환 설정 시 로컬 실패 후 Gemini를 사용합니다.",
    response_description="오늘 옷차림, 판단에 사용한 날씨와 준비물",
)
def get_today(latitude: Latitude, longitude: Longitude, service: OutfitServiceDependency) -> ApiResponse[TodayOutfitResponse]:
    """오늘의 베스트·워스트 옷차림 조회"""
    result = service.get_today(latitude, longitude)
    return ApiResponse(data=TodayOutfitResponse.from_result(result))


@router.get(
    "/weekly", response_model=ApiResponse[WeeklyOutfitResponse],
    summary="7일 옷차림 추천", operation_id="get_weekly_outfits",
    description="매일 한국 시간 새벽 배치에서 준비한 7일 추천을 제공합니다. 조회 시 모델을 호출하지 않습니다. 준비 전에는 OUTFIT_WEEKLY_NOT_READY를 반환하며 forecast_start_date로 예보 기준 날짜를 확인합니다.",
    response_description="7일 추천, 주간 준비 의류와 기온 요약",
)
def get_weekly(latitude: Latitude, longitude: Longitude, service: OutfitServiceDependency) -> ApiResponse[WeeklyOutfitResponse]:
    """7일 옷차림과 공통 준비 의류 조회"""
    result = service.get_weekly(latitude, longitude)
    return ApiResponse(data=WeeklyOutfitResponse.from_result(result))
