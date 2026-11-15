"""좌표·시군구 옷차림 추천과 피드백 API를 관리한다."""

# 표준 라이브러리
from typing import Annotated, Literal
from uuid import UUID

# 외부 라이브러리
from fastapi import APIRouter, Depends, Query, Path

# 프로젝트 모듈
from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.outfits.bootstrap import get_cached_outfit_service, get_region_outfit_service
from app.outfits.feedback_bootstrap import get_feedback_store
from app.outfits.infrastructure.cache import CachedOutfitService
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore
from app.outfits.presentation.schemas import (
    ApproveFeedback,
    CreateFeedback,
    RevisionInput,
    UpdateFeedback,
    TodayOutfitResponse,
    WeeklyOutfitResponse,
    NeighborhoodTodayResponse,
    NeighborhoodWeeklyResponse,
)
from app.outfits.application.services import RegionOutfitService
from app.outfits.domain.models import Activity, ColdSensitivity, OutfitPreferences, OutfitStyle, ClothingPreference, AvoidItem
from app.users.presentation.router import AuthDependency, SessionCookie, private_response, require_browser_request


# 라우터 설정
router = APIRouter()
OUTFIT_RESPONSES = error_responses(
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
)
FEEDBACK_RESPONSES = error_responses(
    ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_FORBIDDEN, ErrorCode.OUTFIT_FEEDBACK_NOT_FOUND,
    ErrorCode.OUTFIT_FEEDBACK_CONFLICT, ErrorCode.OUTFIT_FEEDBACK_INVALID,
)
FEEDBACK_READ_DEPENDENCIES = [Depends(private_response)]
FEEDBACK_WRITE_DEPENDENCIES = [*FEEDBACK_READ_DEPENDENCIES, Depends(require_browser_request)]


# 서비스 의존성
OutfitServiceDependency = Annotated[CachedOutfitService, Depends(get_cached_outfit_service)]
RegionDependency = Annotated[RegionOutfitService, Depends(get_region_outfit_service)]
FeedbackStoreDependency = Annotated[SQLiteFeedbackStore, Depends(get_feedback_store)]


# 요청 매개변수 타입
Latitude = Annotated[float, Query(ge=-90, le=90, allow_inf_nan=False, description="지역 검색 결과의 위도", examples=[37.5665])]
Longitude = Annotated[float, Query(ge=-180, le=180, allow_inf_nan=False, description="지역 검색 결과의 경도", examples=[126.978])]
LocationId = Annotated[int, Path(gt=0, description="국내 지역 검색 API에서 받은 GeoNames 식별자. 공식 행정동 코드가 아님")]


# 개인화 조건 변환
def get_preferences(
    cold_sensitivity: Annotated[ColdSensitivity, Query(description="normal: 보통, cold: 추위를 많이 탐, warm: 더위를 많이 탐")] = ColdSensitivity.NORMAL,
    style: Annotated[OutfitStyle, Query(description="default: 기본, casual: 편안함, formal: 단정함")] = OutfitStyle.DEFAULT,
    activity: Annotated[Activity, Query(description="daily: 일상, outdoor: 야외, active: 활동량 많음")] = Activity.DAILY,
    clothing_preference: Annotated[ClothingPreference, Query(description=(
        "any: 제한 없음, menswear: 남성복 스타일과 공용 의류, womenswear: 여성복 스타일과 공용 의류"
    ))] = ClothingPreference.ANY,
    avoid_items: Annotated[list[AvoidItem] | None, Query(max_length=6, description="추천에서 피할 의류. 같은 이름의 쿼리로 여러 항목 전달")] = None,
) -> OutfitPreferences:
    """개인 조건은 요청으로 받고 공통 추천 캐시 키에는 포함하지 않는다."""
    return OutfitPreferences(cold_sensitivity, style, activity, clothing_preference, tuple(avoid_items or ()))


# 개인화 의존성: 조건 변환 함수 정의 후 생성
PreferencesDependency = Annotated[OutfitPreferences, Depends(get_preferences)]


# 옷차림 조회 API
@router.get(
    "/outfits/today", response_model=ApiResponse[TodayOutfitResponse],
    tags=["outfits"], responses=OUTFIT_RESPONSES,
    summary="오늘 옷차림 추천", operation_id="get_today_outfit",
    description="저장된 오늘 추천을 제공하고 조회한 지역은 매시간 갱신합니다. 최초 조회는 생성 시간이 필요합니다. 자동 전환 설정 시 로컬 실패 후 Gemini를 사용합니다.",
    response_description="오늘 옷차림, 판단에 사용한 날씨와 준비물",
)
def get_today(latitude: Latitude, longitude: Longitude, service: OutfitServiceDependency) -> ApiResponse[TodayOutfitResponse]:
    """오늘의 베스트·워스트 옷차림 조회"""
    result = service.get_today(latitude, longitude)
    return ApiResponse(data=TodayOutfitResponse.from_result(result))


@router.get(
    "/outfits/weekly", response_model=ApiResponse[WeeklyOutfitResponse],
    tags=["outfits"], responses=OUTFIT_RESPONSES,
    summary="7일 옷차림 추천", operation_id="get_weekly_outfits",
    description="매일 한국 시간 새벽 배치에서 준비한 7일 추천을 제공합니다. 조회 시 모델을 호출하지 않습니다. 준비 전에는 OUTFIT_WEEKLY_NOT_READY를 반환하며 forecast_start_date로 예보 기준 날짜를 확인합니다.",
    response_description="7일 추천, 주간 준비 의류와 기온 요약",
)
def get_weekly(latitude: Latitude, longitude: Longitude, service: OutfitServiceDependency) -> ApiResponse[WeeklyOutfitResponse]:
    """7일 옷차림과 공통 준비 의류 조회"""
    result = service.get_weekly(latitude, longitude)
    return ApiResponse(data=WeeklyOutfitResponse.from_result(result))


@router.get(
    "/outfits/regions/{location_id}/today", response_model=ApiResponse[NeighborhoodTodayResponse],
    tags=["outfits"], responses=OUTFIT_RESPONSES,
    summary="동네 공통 오늘 추천과 개인화", operation_id="get_neighborhood_today_outfit",
    description="공통 추천을 공유하고 개인 조건별 자연어 추천을 별도로 생성·저장합니다. 최근 조건은 공통 갱신 10분 전부터 준비하며 최초 조합은 생성 시간이 필요합니다.",
)
def get_region_today(
    location_id: LocationId, service: RegionDependency, preferences: PreferencesDependency,
) -> ApiResponse[NeighborhoodTodayResponse]:
    """동네 공통 오늘 추천의 개인화 복사본 반환"""
    return ApiResponse(data=NeighborhoodTodayResponse.from_region(service.get_today(location_id, preferences)))


@router.get(
    "/outfits/regions/{location_id}/weekly", response_model=ApiResponse[NeighborhoodWeeklyResponse],
    tags=["outfits"], responses=OUTFIT_RESPONSES,
    summary="동네 공통 주간 추천과 개인화", operation_id="get_neighborhood_weekly_outfits",
    description="매일 새벽 배치에서 생성한 시군구 공통·개인 주간 결과를 조회합니다. 새 조건은 다음 배치 대상으로 등록하고 준비 전에는 OUTFIT_WEEKLY_NOT_READY를 반환합니다.",
)
def get_region_weekly(
    location_id: LocationId, service: RegionDependency, preferences: PreferencesDependency,
) -> ApiResponse[NeighborhoodWeeklyResponse]:
    """동네 공통 주간 추천과 개인별 준비 의류 반환"""
    return ApiResponse(data=NeighborhoodWeeklyResponse.from_region(service.get_weekly(location_id, preferences)))


def get_feedback_owner(service: AuthDependency, token: SessionCookie = None) -> str:
    return str(service.authenticate(token).id)


FeedbackOwner = Annotated[str, Depends(get_feedback_owner)]


@router.post(
    "/outfit-feedback", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_WRITE_DEPENDENCIES, status_code=201, summary="내 답변 문제 신고와 수정안 등록",
)
def create(body: CreateFeedback, user: FeedbackOwner, store: FeedbackStoreDependency) -> ApiResponse[dict]:
    """보존된 생성 원본과 날짜로 본인의 신고를 등록합니다. 수정안은 승인되지 않은 초안으로 저장합니다."""
    corrected_day = body.corrected_day.model_dump(mode="json") if body.corrected_day else None
    return ApiResponse(data=store.create(
        user, str(body.generation_id), body.date.isoformat(), body.issues, body.note, corrected_day,
    ))


@router.get(
    "/outfit-feedback", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_READ_DEPENDENCIES, summary="내 신고와 수정안 목록",
)
def list_feedback(
    user: FeedbackOwner,
    store: FeedbackStoreDependency,
    status: Literal["reported", "draft", "approved", "rejected"] | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApiResponse[dict]:
    """현재 로그인한 본인의 신고만 상태별로 조회합니다. 다른 계정의 신고는 반환하지 않습니다."""
    return ApiResponse(data=store.list(user, status=status, limit=limit, offset=offset))


@router.get(
    "/outfit-feedback/export", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_READ_DEPENDENCIES, summary="내 승인 정답 학습자료 내보내기",
)
def export(user: FeedbackOwner, store: FeedbackStoreDependency) -> ApiResponse[dict]:
    """본인이 명시적으로 승인한 수정 정답만 반환합니다. 계정 식별자와 메모는 제외하며 학습은 실행하지 않습니다."""
    records = store.export_records(user)
    return ApiResponse(data={"records": records, "count": len(records), "format": "sft+preference"})


@router.get(
    "/outfit-feedback/{identifier}", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_READ_DEPENDENCIES, summary="내 수정안 원본과 검증 결과 조회",
)
def detail(identifier: UUID, user: FeedbackOwner, store: FeedbackStoreDependency) -> ApiResponse[dict]:
    """본인의 신고에 연결된 원본 답변, 날씨, 수정안과 검증 결과를 함께 조회합니다."""
    return ApiResponse(data=store.get(user, str(identifier)))


@router.put(
    "/outfit-feedback/{identifier}", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_WRITE_DEPENDENCIES, summary="내 수정안 초안 편집",
)
def update(
    identifier: UUID, body: UpdateFeedback, user: FeedbackOwner, store: FeedbackStoreDependency,
) -> ApiResponse[dict]:
    """현재 버전이 일치할 때만 수정안을 저장합니다. 편집하면 기존 승인이 해제되며 원본은 보존합니다."""
    corrected_day = body.corrected_day.model_dump(mode="json") if body.corrected_day else None
    return ApiResponse(data=store.update(
        user, str(identifier), body.revision, body.issues, body.note, corrected_day,
    ))


@router.post(
    "/outfit-feedback/{identifier}/approve", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_WRITE_DEPENDENCIES, summary="내 수정 정답 검수 승인",
)
def approve(
    identifier: UUID, body: ApproveFeedback, user: FeedbackOwner, store: FeedbackStoreDependency,
) -> ApiResponse[dict]:
    """형식과 필수 검증을 통과한 본인의 수정안을 확인 후 승인합니다. 승인된 정답만 내보내기에 포함됩니다."""
    return ApiResponse(data=store.review(user, str(identifier), body.revision, approved=True, confirmed=body.confirmed))


@router.post(
    "/outfit-feedback/{identifier}/reject", tags=["outfit-feedback"], responses=FEEDBACK_RESPONSES,
    dependencies=FEEDBACK_WRITE_DEPENDENCIES, summary="내 수정안 검수 거절",
)
def reject(
    identifier: UUID, body: RevisionInput, user: FeedbackOwner, store: FeedbackStoreDependency,
) -> ApiResponse[dict]:
    """본인의 수정안을 거절 상태로 바꾸고 학습자료 내보내기에서 제외합니다. 변경 이력은 보존합니다."""
    return ApiResponse(data=store.review(user, str(identifier), body.revision, approved=False))
