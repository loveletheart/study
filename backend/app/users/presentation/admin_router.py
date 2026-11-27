"""관리자 페이지에서 사용하는 권한 확인 API."""

from fastapi import APIRouter, Depends, Response

from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
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
    private_response(response)
    return ApiResponse(data={"authorized": True})
