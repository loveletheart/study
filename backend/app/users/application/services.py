"""사용자 기능의 처리 순서와 트랜잭션 범위를 관리한다."""

# 표준 라이브러리
from uuid import UUID

# 프로젝트 모듈
from app.users.application.dto import CreateUserCommand, UserDTO
from app.users.application.exceptions import UserNotFoundError
from app.users.application.unit_of_work import UserUnitOfWork
from app.users.domain.entities import User
from app.users.domain.exceptions import DuplicateEmailError


class UserService:
    def __init__(self, unit_of_work: UserUnitOfWork) -> None:
        """사용자 작업 단위 주입"""
        self._unit_of_work = unit_of_work

    def create_user(self, command: CreateUserCommand) -> UserDTO:
        """중복 확인 후 사용자 저장"""
        user = User(name=command.name, email=command.email)
        with self._unit_of_work as uow:
            if uow.users.find_by_email(user.email) is not None:
                raise DuplicateEmailError()
            uow.users.add(user)
            uow.commit()
        return UserDTO.from_entity(user)

    def get_user(self, user_id: UUID) -> UserDTO:
        """UUID로 사용자 조회"""
        with self._unit_of_work as uow:
            user = uow.users.find_by_id(user_id)
            if user is None:
                raise UserNotFoundError()
        return UserDTO.from_entity(user)
