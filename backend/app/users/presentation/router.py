# 표준 라이브러리
from typing import Annotated
from uuid import UUID

# 외부 라이브러리
from fastapi import APIRouter, Depends, Path, Response, Request, Cookie, status

# 프로젝트 모듈
from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.common.config import get_settings
from app.users.application.dto import CreateUserCommand
from app.users.application.services import UserService
from app.users.bootstrap import get_user_service, get_auth_service
from app.users.application.services import AuthService
from app.users.application.exceptions import AuthorizationError
from app.users.presentation.schemas import CreateUserRequest, UserResponse, LoginRequest, RegisterRequest, ProfileRequest, AccountResponse


# 라우터 설정
router = APIRouter(prefix="/users", tags=["users"], responses=error_responses(
    ErrorCode.AUTH_REQUIRED, ErrorCode.AUTH_INVALID_CREDENTIALS, ErrorCode.AUTH_FORBIDDEN,
    ErrorCode.AUTH_RATE_LIMITED, ErrorCode.USER_DUPLICATE_EMAIL, ErrorCode.USER_INVALID_DATA,
    ErrorCode.WEATHER_INVALID_QUERY,
))


# 서비스 의존성
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]
AuthDependency = Annotated[AuthService, Depends(get_auth_service)]
SessionCookie = Annotated[str | None, Cookie(alias="ondo_session")]


def require_browser_request(request: Request) -> None:
    """전용 헤더와 동일 사이트 조건으로 브라우저의 변경 요청을 확인한다."""
    if request.headers.get("X-Ondo-Request") != "1" or request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise AuthorizationError()


def require_owner(user_id: UUID, service: AuthDependency, token: SessionCookie = None) -> None:
    """로그인한 본인의 정보만 조회한다."""
    if service.authenticate(token).id != user_id:
        raise AuthorizationError()


def private_response(response: Response) -> None:
    """개인 응답을 브라우저와 중간 캐시에 저장하지 않는다."""
    response.headers["Cache-Control"] = "no-store"


def set_session(response: Response, token: str) -> None:
    """확인된 세션을 HTTP 전용 쿠키로 발급한다."""
    response.set_cookie("ondo_session", token, max_age=AuthService.SESSION_SECONDS, httponly=True,
                        secure=get_settings().session_cookie_secure, samesite="lax", path="/api/v1")
    private_response(response)


@router.post("/auth/register", response_model=ApiResponse[AccountResponse], status_code=201, summary="회원가입과 로그인", dependencies=[Depends(require_browser_request)])
def register(body: RegisterRequest, request: Request, response: Response, service: AuthDependency, token: SessionCookie = None):
    """닉네임·이메일·비밀번호로 가입하고 세션 쿠키를 발급합니다. 추천 프로필은 별도로 저장합니다."""
    account, session = service.register(body.name, body.email, body.password.get_secret_value(), request.client.host if request.client else "unknown", token)
    set_session(response, session)
    return ApiResponse(data=AccountResponse.from_account(account))


@router.post("/auth/login", response_model=ApiResponse[AccountResponse], summary="이메일과 비밀번호 로그인", dependencies=[Depends(require_browser_request)])
def login(body: LoginRequest, request: Request, response: Response, service: AuthDependency, token: SessionCookie = None):
    """이메일·비밀번호를 확인하고 현재 브라우저 세션을 교체합니다. 없는 계정과 잘못된 비밀번호는 같은 안내를 반환합니다."""
    account, session = service.login(body.email, body.password.get_secret_value(), request.client.host if request.client else "unknown", token)
    set_session(response, session)
    return ApiResponse(data=AccountResponse.from_account(account))


@router.post("/auth/logout", summary="현재 브라우저 로그아웃", dependencies=[Depends(require_browser_request)])
def logout(response: Response, service: AuthDependency, token: SessionCookie = None) -> ApiResponse[dict[str, bool]]:
    """현재 브라우저 세션을 폐기하고 쿠키를 삭제합니다."""
    service.logout(token)
    response.delete_cookie("ondo_session", path="/api/v1", httponly=True, samesite="lax", secure=get_settings().session_cookie_secure)
    private_response(response)
    return ApiResponse(data={"logged_out": True})


@router.get("/me", response_model=ApiResponse[AccountResponse], summary="내 계정과 추천 프로필")
def me(response: Response, service: AuthDependency, token: SessionCookie = None):
    """로그인한 본인의 기본 정보와 저장된 지역·추천 조건을 반환합니다."""
    private_response(response)
    return ApiResponse(data=AccountResponse.from_account(service.me(token)))


@router.put("/me/profile", response_model=ApiResponse[AccountResponse], summary="내 추천 프로필 저장", dependencies=[Depends(require_browser_request)])
def save_profile(body: ProfileRequest, response: Response, service: AuthDependency, token: SessionCookie = None):
    """검색에서 검증된 지역과 추천 조건을 본인 계정에 저장합니다. 저장만으로 모델을 호출하지 않습니다."""
    private_response(response)
    return ApiResponse(data=AccountResponse.from_account(service.save_profile(token, body.name, body.to_domain())))


# 사용자 API
@router.post(
    "",
    response_model=ApiResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
    summary="사용자 등록",
    description="이름과 이메일로 사용자를 등록합니다. 중복 이메일은 허용하지 않습니다.",
    response_description="생성된 사용자 정보. Location 헤더에 조회 경로를 반환합니다.",
    operation_id="create_user",
    responses=error_responses(ErrorCode.USER_DUPLICATE_EMAIL, ErrorCode.USER_INVALID_DATA),
)
def create_user(
    body: CreateUserRequest,
    service: UserServiceDependency,
    response: Response,
) -> ApiResponse[UserResponse]:
    """이름과 이메일로 사용자 등록"""
    result = service.create_user(CreateUserCommand(name=body.name, email=body.email))
    response.headers["Location"] = f"/api/v1/users/{result.id}"
    return ApiResponse(data=UserResponse.model_validate(result))


@router.get(
    "/{user_id}",
    dependencies=[Depends(require_owner), Depends(private_response)],
    response_model=ApiResponse[UserResponse],
    summary="사용자 단건 조회",
    description="로그인한 본인의 UUID로 이름과 이메일을 조회합니다.",
    response_description="UUID에 해당하는 사용자 정보",
    operation_id="get_user",
    responses=error_responses(ErrorCode.USER_NOT_FOUND),
)
def get_user(
    user_id: Annotated[UUID, Path(description="사용자 등록 응답에서 받은 UUID")],
    service: UserServiceDependency,
) -> ApiResponse[UserResponse]:
    """UUID로 사용자 정보 조회"""
    result = service.get_user(user_id)
    return ApiResponse(data=UserResponse.model_validate(result))
