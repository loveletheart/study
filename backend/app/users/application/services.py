"""사용자 기능의 처리 순서와 트랜잭션 범위를 관리한다."""

# 표준 라이브러리
from uuid import UUID
import hashlib
import secrets
import time
from typing import Callable

# 프로젝트 모듈
from app.users.application.dto import CreateUserCommand, UserDTO
from app.users.application.exceptions import UserNotFoundError
from app.users.application.unit_of_work import UserUnitOfWork
from app.users.domain.entities import User
from app.users.domain.exceptions import DuplicateEmailError
from app.users.domain.exceptions import InvalidUserError
from app.users.application.dto import AccountDTO, RecommendationProfile
from app.users.application.exceptions import AuthenticationRequiredError, InvalidCredentialsError
from app.users.application.ports import AuthStore, PasswordSecurity
from app.weather.application.ports import LocationCatalog


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


class AuthService:
    SESSION_SECONDS = 7 * 86400

    def __init__(self, store: AuthStore, passwords: PasswordSecurity, locations: LocationCatalog, clock: Callable[[], float] = time.time) -> None:
        self._store, self._passwords, self._locations, self._clock = store, passwords, locations, clock

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _limit(self, email: str, peer: str) -> None:
        self._store.consume_attempts(((self._token_hash("peer:" + peer), 30), (self._token_hash("email:" + email), 10)), self._clock())

    def register(self, name: str, email: str, password: str, peer: str, previous: str | None = None) -> tuple[AccountDTO, str]:
        user = User(name=name, email=email)
        if not 10 <= len(password) <= 128:
            raise InvalidUserError("비밀번호는 공백을 포함해 10~128자여야 합니다.")
        self._limit(user.email, peer)
        self._store.create_account(user, self._passwords.hash(password))
        return self._start_session(user, previous)

    def login(self, email: str, password: str, peer: str, previous: str | None = None) -> tuple[AccountDTO, str]:
        email = email.strip().casefold()
        self._limit(email, peer)
        record = self._store.credentials(email)
        if not self._passwords.verify(password, record[1] if record else None) or record is None:
            raise InvalidCredentialsError()
        return self._start_session(record[0], previous)

    def _start_session(self, user: User, previous: str | None) -> tuple[AccountDTO, str]:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._store.create_session(user.id, self._token_hash(token), now + self.SESSION_SECONDS, now, self._token_hash(previous) if previous else None)
        return self._account(user), token

    def authenticate(self, token: str | None) -> User:
        user = self._store.session_user(self._token_hash(token), self._clock()) if token and len(token) == 43 else None
        if user is None:
            raise AuthenticationRequiredError()
        return user

    def _account(self, user: User) -> AccountDTO:
        profile = self._store.profile(user.id)
        location = self._locations.get(profile.location_id) if profile.location_id is not None else None
        return AccountDTO(UserDTO.from_entity(user), location, profile.preferences)

    def me(self, token: str | None) -> AccountDTO:
        return self._account(self.authenticate(token))

    def save_profile(self, token: str | None, name: str, profile: RecommendationProfile) -> AccountDTO:
        original = self.authenticate(token)
        user = User(id=original.id, name=name, email=original.email)
        if profile.location_id is not None:
            self._locations.get(profile.location_id)
        self._store.save_profile(user, profile)
        return self._account(user)

    def logout(self, token: str | None) -> None:
        if token:
            self._store.delete_session(self._token_hash(token))
