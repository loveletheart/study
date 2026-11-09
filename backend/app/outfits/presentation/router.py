"""좌표·시군구 오늘/주간 옷차림 API를 한 라우터에서 관리한다."""

# 표준 라이브러리
from typing import Annotated

# 외부 라이브러리
from fastapi import APIRouter, Depends, Query, Path

# 프로젝트 모듈
from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.outfits.bootstrap import get_cached_outfit_service, get_region_outfit_service
from app.outfits.infrastructure.cache import CachedOutfitService
from app.outfits.presentation.schemas import (
    TodayOutfitResponse,
    WeeklyOutfitResponse,
    NeighborhoodTodayResponse,
    NeighborhoodWeeklyResponse,
)
from app.outfits.application.services import RegionOutfitService
from app.outfits.domain.models import Activity, ColdSensitivity, OutfitPreferences, OutfitStyle, ClothingPreference, AvoidItem


# 라우터 설정
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


# 서비스 의존성
OutfitServiceDependency = Annotated[CachedOutfitService, Depends(get_cached_outfit_service)]
RegionDependency = Annotated[RegionOutfitService, Depends(get_region_outfit_service)]


# 요청 매개변수 타입
Latitude = Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False, description="지역 검색 결과의 위도", examples=[37.5665])]
Longitude = Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False, description="지역 검색 결과의 경도", examples=[126.978])]
LocationId = Annotated[int, Path(gt=0, description="국내 지역 검색 API에서 받은 GeoNames 식별자. 공식 행정동 코드가 아님")]


# 개인화 조건 변환
def get_preferences(
    cold_sensitivity: Annotated[ColdSensitivity, Query(description="normal: 보통, cold: 추위를 많이 탐, warm: 더위를 많이 탐")] = ColdSensitivity.NORMAL,
    style: Annotated[OutfitStyle, Query(description="default: 기본, casual: 편안함, formal: 단정함")] = OutfitStyle.DEFAULT,
    activity: Annotated[Activity, Query(description="daily: 일상, outdoor: 야외, active: 활동량 많음")] = Activity.DAILY,
    clothing_preference: Annotated[ClothingPreference, Query(description="any: 제한 없음, menswear: 남성복 위주, womenswear: 여성복 위주")] = ClothingPreference.ANY,
    avoid_items: Annotated[list[AvoidItem] | None, Query(max_length=6, description="추천에서 피할 의류. 같은 이름의 쿼리로 여러 항목 전달")] = None,
) -> OutfitPreferences:
    """개인 조건은 요청으로 받고 공통 추천 캐시 키에는 포함하지 않는다."""
    return OutfitPreferences(cold_sensitivity, style, activity, clothing_preference, tuple(avoid_items or ()))


# 개인화 의존성: 조건 변환 함수 정의 후 생성
PreferencesDependency = Annotated[OutfitPreferences, Depends(get_preferences)]


# 옷차림 조회 API
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


@router.get(
    "/regions/{location_id}/today", response_model=ApiResponse[NeighborhoodTodayResponse],
    summary="동네 공통 오늘 추천과 개인화", operation_id="get_neighborhood_today_outfit",
    description="공통 추천을 공유하고 개인 조건별 자연어 추천을 별도로 생성·저장합니다. 최근 조건은 공통 갱신 10분 전부터 준비하며 최초 조합은 생성 시간이 필요합니다.",
)
def get_region_today(
    location_id: LocationId, service: RegionDependency, preferences: PreferencesDependency,
) -> ApiResponse[NeighborhoodTodayResponse]:
    """동네 공통 오늘 추천의 개인화 복사본 반환"""
    return ApiResponse(data=NeighborhoodTodayResponse.from_region(service.get_today(location_id, preferences)))


@router.get(
    "/regions/{location_id}/weekly", response_model=ApiResponse[NeighborhoodWeeklyResponse],
    summary="동네 공통 주간 추천과 개인화", operation_id="get_neighborhood_weekly_outfits",
    description="매일 새벽 배치에서 생성한 시군구 공통·개인 주간 결과를 조회합니다. 새 조건은 다음 배치 대상으로 등록하고 준비 전에는 OUTFIT_WEEKLY_NOT_READY를 반환합니다.",
)
def get_region_weekly(
    location_id: LocationId, service: RegionDependency, preferences: PreferencesDependency,
) -> ApiResponse[NeighborhoodWeeklyResponse]:
    """동네 공통 주간 추천과 개인별 준비 의류 반환"""
    return ApiResponse(data=NeighborhoodWeeklyResponse.from_region(service.get_weekly(location_id, preferences)))
