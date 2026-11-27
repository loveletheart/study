"""관리자 페이지에서 사용하는 운영 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.common.config import Settings, get_settings
from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.users.application.dto import AdminOverview
from app.users.infrastructure.admin_overview import read_admin_overview
from app.users.presentation.router import AuthDependency, SessionCookie, private_response


def require_admin(service: AuthDependency, token: SessionCookie = None) -> None:
    service.require_admin(token)


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
    responses=error_responses(ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_SESSION_EXPIRED, ErrorCode.AUTH_FORBIDDEN),
)


@router.get("/access", summary="관리자 페이지 접근 권한 확인")
def check_access(response: Response) -> ApiResponse[dict[str, bool]]:
    """현재 세션의 계정에 관리자 권한이 있는지 확인합니다."""
    private_response(response)
    return ApiResponse(data={"authorized": True})


@router.get("/overview", summary="가입 계정·추천 피드백·최근 주간 배치 현황")
def overview(response: Response, settings: Annotated[Settings, Depends(get_settings)]) -> ApiResponse[AdminOverview]:
    """관리자에게 가입 계정 수, 추천 피드백 집계, 최근 7개 주간 배치 실행을 제공합니다."""
    private_response(response)
    return ApiResponse(data=read_admin_overview(settings.database_path))
