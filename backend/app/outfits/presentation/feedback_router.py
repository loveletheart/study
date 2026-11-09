from datetime import date as Date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from app.common.responses import ApiResponse
from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.outfits.feedback_bootstrap import get_feedback_store
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore
from app.outfits.infrastructure.schemas import GeneratedDay
from app.users.presentation.router import AuthDependency, SessionCookie, require_browser_request, private_response

router = APIRouter(prefix='/outfit-feedback', tags=['outfit-feedback'], dependencies=[Depends(private_response)], responses=error_responses(
    ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_FORBIDDEN, ErrorCode.OUTFIT_FEEDBACK_NOT_FOUND,
    ErrorCode.OUTFIT_FEEDBACK_CONFLICT, ErrorCode.OUTFIT_FEEDBACK_INVALID,
))
Store = Annotated[SQLiteFeedbackStore, Depends(get_feedback_store)]
Issue = Literal['clothing_category', 'weather_logic', 'explanation_mismatch', 'preference_mismatch', 'repetition', 'other']


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issues: list[Issue] = Field(min_length=1, max_length=6)
    note: str = Field(default='', max_length=2000)
    corrected_day: GeneratedDay | None = None


class CreateFeedback(FeedbackInput):
    generation_id: UUID
    date: Date


class UpdateFeedback(FeedbackInput):
    revision: int = Field(ge=1)


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(ge=1)


class ApproveFeedback(RevisionInput):
    confirmed: Literal[True]


def owner(service: AuthDependency, token: SessionCookie = None) -> str:
    return str(service.authenticate(token).id)


Owner = Annotated[str, Depends(owner)]


@router.post('', status_code=201, summary='내 답변 문제 신고와 수정안 등록', dependencies=[Depends(require_browser_request)])
def create(body: CreateFeedback, user: Owner, store: Store) -> ApiResponse[dict]:
    """보존된 생성 원본과 날짜로 본인의 신고를 등록합니다. 수정안은 승인되지 않은 초안으로 저장합니다."""
    return ApiResponse(data=store.create(user, str(body.generation_id), body.date.isoformat(), body.issues, body.note, body.corrected_day.model_dump(mode='json') if body.corrected_day else None))


@router.get('', summary='내 신고와 수정안 목록')
def list_feedback(user: Owner, store: Store, status: Literal['reported', 'draft', 'approved', 'rejected'] | None = None,
                  limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> ApiResponse[dict]:
    """현재 로그인한 본인의 신고만 상태별로 조회합니다. 다른 계정의 신고는 반환하지 않습니다."""
    return ApiResponse(data=store.list(user, status=status, limit=limit, offset=offset))


@router.get('/export', summary='내 승인 정답 학습자료 내보내기')
def export(user: Owner, store: Store) -> ApiResponse[dict]:
    """본인이 명시적으로 승인한 수정 정답만 반환합니다. 계정 식별자와 메모는 제외하며 학습은 실행하지 않습니다."""
    records = store.export_records(user)
    return ApiResponse(data={'records': records, 'count': len(records), 'format': 'sft+preference'})


@router.get('/{identifier}', summary='내 수정안 원본과 검증 결과 조회')
def detail(identifier: UUID, user: Owner, store: Store) -> ApiResponse[dict]:
    """본인의 신고에 연결된 원본 답변, 날씨, 수정안과 검증 결과를 함께 조회합니다."""
    return ApiResponse(data=store.get(user, str(identifier)))


@router.put('/{identifier}', summary='내 수정안 초안 편집', dependencies=[Depends(require_browser_request)])
def update(identifier: UUID, body: UpdateFeedback, user: Owner, store: Store) -> ApiResponse[dict]:
    """현재 버전이 일치할 때만 수정안을 저장합니다. 편집하면 기존 승인이 해제되며 원본은 보존합니다."""
    return ApiResponse(data=store.update(user, str(identifier), body.revision, body.issues, body.note, body.corrected_day.model_dump(mode='json') if body.corrected_day else None))


@router.post('/{identifier}/approve', summary='내 수정 정답 검수 승인', dependencies=[Depends(require_browser_request)])
def approve(identifier: UUID, body: ApproveFeedback, user: Owner, store: Store) -> ApiResponse[dict]:
    """형식과 필수 검증을 통과한 본인의 수정안을 확인 후 승인합니다. 승인된 정답만 내보내기에 포함됩니다."""
    return ApiResponse(data=store.review(user, str(identifier), body.revision, approved=True, confirmed=body.confirmed))


@router.post('/{identifier}/reject', summary='내 수정안 검수 거절', dependencies=[Depends(require_browser_request)])
def reject(identifier: UUID, body: RevisionInput, user: Owner, store: Store) -> ApiResponse[dict]:
    """본인의 수정안을 거절 상태로 바꾸고 학습자료 내보내기에서 제외합니다. 변경 이력은 보존합니다."""
    return ApiResponse(data=store.review(user, str(identifier), body.revision, approved=False))
