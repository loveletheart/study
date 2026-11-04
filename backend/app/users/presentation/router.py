"""HTTP 처리와 애플리케이션 호출. SQL은 이 계층에서 사용하지 않는다."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.users.application.dto import CreateUserCommand
from app.users.application.exceptions import UserNotFoundError
from app.users.application.services import UserService
from app.users.bootstrap import get_user_service
from app.users.domain.exceptions import DuplicateEmailError, InvalidUserError
from app.users.presentation.schemas import CreateUserRequest, UserResponse

router = APIRouter(prefix="/users", tags=["users"])
UserServiceDependency = Annotated[UserService, Depends(get_user_service)]


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"description": "이미 등록된 이메일"}},
)
def create_user(
    body: CreateUserRequest,
    service: UserServiceDependency,
    response: Response,
) -> UserResponse:
    try:
        result = service.create_user(CreateUserCommand(name=body.name, email=body.email))
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidUserError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Location"] = f"/api/v1/users/{result.id}"
    return UserResponse.model_validate(result)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses={404: {"description": "사용자가 존재하지 않음"}},
)
def get_user(user_id: UUID, service: UserServiceDependency) -> UserResponse:
    try:
        result = service.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return UserResponse.model_validate(result)
