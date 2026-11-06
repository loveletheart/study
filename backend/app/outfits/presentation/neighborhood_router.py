from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.common.responses import ApiResponse
from app.outfits.application.services.neighborhood_service import NeighborhoodOutfitService
from app.outfits.bootstrap import get_neighborhood_outfit_service
from app.outfits.domain.preferences import Activity, ColdSensitivity, OutfitPreferences, OutfitStyle
from app.outfits.presentation.neighborhood_schemas import NeighborhoodTodayResponse, NeighborhoodWeeklyResponse
from app.outfits.presentation.router import router as coordinate_router

router = APIRouter(prefix="/outfits/regions", tags=["outfits"], responses=coordinate_router.responses)
NeighborhoodDependency = Annotated[NeighborhoodOutfitService, Depends(get_neighborhood_outfit_service)]
LocationId = Annotated[int, Path(gt=0, description="국내 지역 검색 API에서 받은 GeoNames 식별자. 공식 행정동 코드가 아님")]


def get_preferences(
    cold_sensitivity: Annotated[ColdSensitivity, Query(description="normal: 보통, cold: 추위를 많이 탐, warm: 더위를 많이 탐")] = ColdSensitivity.NORMAL,
    style: Annotated[OutfitStyle, Query(description="default: 기본, casual: 편안함, formal: 단정함")] = OutfitStyle.DEFAULT,
    activity: Annotated[Activity, Query(description="daily: 일상, outdoor: 야외, active: 활동량 많음")] = Activity.DAILY,
) -> OutfitPreferences:
    """개인 조건은 요청으로 받고 공통 추천 캐시 키에는 포함하지 않는다."""
    return OutfitPreferences(cold_sensitivity, style, activity)


PreferencesDependency = Annotated[OutfitPreferences, Depends(get_preferences)]


@router.get(
    "/{location_id}/today", response_model=ApiResponse[NeighborhoodTodayResponse],
    summary="동네 공통 오늘 추천과 개인화", operation_id="get_neighborhood_today_outfit",
    description="공통 추천을 공유하고 개인 조건별 자연어 추천을 별도로 생성·저장합니다. 최근 조건은 공통 갱신 10분 전부터 준비하며 최초 조합은 생성 시간이 필요합니다.",
)
def get_today(
    location_id: LocationId, service: NeighborhoodDependency, preferences: PreferencesDependency,
) -> ApiResponse[NeighborhoodTodayResponse]:
    """동네 공통 오늘 추천의 개인화 복사본 반환"""
    return ApiResponse(data=NeighborhoodTodayResponse.from_neighborhood(service.get_today(location_id, preferences)))


@router.get(
    "/{location_id}/weekly", response_model=ApiResponse[NeighborhoodWeeklyResponse],
    summary="동네 공통 주간 추천과 개인화", operation_id="get_neighborhood_weekly_outfits",
    description="매일 새벽 배치에서 생성한 시군구 공통·개인 주간 결과를 조회합니다. 새 조건은 다음 배치 대상으로 등록하고 준비 전에는 OUTFIT_WEEKLY_NOT_READY를 반환합니다.",
)
def get_weekly(
    location_id: LocationId, service: NeighborhoodDependency, preferences: PreferencesDependency,
) -> ApiResponse[NeighborhoodWeeklyResponse]:
    """동네 공통 주간 추천과 개인별 준비 의류 반환"""
    return ApiResponse(data=NeighborhoodWeeklyResponse.from_neighborhood(service.get_weekly(location_id, preferences)))
