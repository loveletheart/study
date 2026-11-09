"""Repository와 트랜잭션 구현체를 Service에 연결하는 조립 지점."""

# 프로젝트 모듈
from app.common.config import get_settings
from app.users.application.services import UserService
from app.users.infrastructure.unit_of_work import SQLiteUserUnitOfWork
from app.users.application.services import AuthService
from app.users.infrastructure.repositories import SQLiteAuthRepository
from app.users.infrastructure.security import ScryptPasswordSecurity
from app.weather.infrastructure.location_catalog import SQLiteLocationCatalog


def get_user_service() -> UserService:
    """저장소와 사용자 서비스 연결"""
    unit_of_work = SQLiteUserUnitOfWork(get_settings().database_path)
    return UserService(unit_of_work)


def get_auth_service() -> AuthService:
    """인증·프로필은 같은 DB의 독립 테이블을 사용한다."""
    database_path = get_settings().database_path
    return AuthService(SQLiteAuthRepository(database_path), ScryptPasswordSecurity(), SQLiteLocationCatalog(database_path))
