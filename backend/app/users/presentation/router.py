from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status

from app.common.errors.codes import ErrorCode
from app.common.errors.openapi import error_responses
from app.common.responses import ApiResponse
from app.users.application.dto import CreateUserCommand
from app.users.application.services import UserService
from app.users.bootstrap import get_user_service
from app.users.presentation.schemas import CreateUserRequest, UserResponse

router = APIRouter(prefix="/users", tags=["users"])
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]


"""이름과 이메일로 사용자 등록"""
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
    result = service.create_user(CreateUserCommand(name=body.name, email=body.email))
    response.headers["Location"] = f"/api/v1/users/{result.id}"
    return ApiResponse(data=UserResponse.model_validate(result))


"""UUID로 사용자 정보 조회"""
@router.get(
    "/{user_id}",
    response_model=ApiResponse[UserResponse],
    summary="사용자 단건 조회",
    description="사용자 UUID로 이름과 이메일을 조회합니다.",
    response_description="UUID에 해당하는 사용자 정보",
    operation_id="get_user",
    responses=error_responses(ErrorCode.USER_NOT_FOUND),
)
def get_user(
    user_id: Annotated[UUID, Path(description="사용자 등록 응답에서 받은 UUID")],
    service: UserServiceDependency,
) -> ApiResponse[UserResponse]:
    result = service.get_user(user_id)
    return ApiResponse(data=UserResponse.model_validate(result))
