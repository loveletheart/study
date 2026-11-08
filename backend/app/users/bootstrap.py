"""Repository와 트랜잭션 구현체를 Service에 연결하는 조립 지점."""

# 프로젝트 모듈
from app.common.config import get_settings
from app.users.application.services import UserService
from app.users.infrastructure.unit_of_work import SQLiteUserUnitOfWork


def get_user_service() -> UserService:
    """저장소와 사용자 서비스 연결"""
    unit_of_work = SQLiteUserUnitOfWork(get_settings().database_path)
    return UserService(unit_of_work)
