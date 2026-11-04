"""사용자 기능의 처리 순서와 트랜잭션 범위를 관리한다."""

from uuid import UUID

from app.users.application.dto import CreateUserCommand, UserDTO
from app.users.application.exceptions import UserNotFoundError
from app.users.application.unit_of_work import UserUnitOfWork
from app.users.domain.entities import User
from app.users.domain.exceptions import DuplicateEmailError


class UserService:
    # 사용자 작업 단위 주입
    def __init__(self, unit_of_work: UserUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    # 중복 확인 후 사용자 저장
    def create_user(self, command: CreateUserCommand) -> UserDTO:
        user = User(name=command.name, email=command.email)
        with self._unit_of_work as uow:
            if uow.users.find_by_email(user.email) is not None:
                raise DuplicateEmailError()
            uow.users.add(user)
            uow.commit()
        return UserDTO.from_entity(user)

    # UUID로 사용자 조회
    def get_user(self, user_id: UUID) -> UserDTO:
        with self._unit_of_work as uow:
            user = uow.users.find_by_id(user_id)
            if user is None:
                raise UserNotFoundError()
        return UserDTO.from_entity(user)
