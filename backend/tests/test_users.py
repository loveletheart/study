"""실제 SQLite DB로 저장·중복·롤백 동작을 검증한다."""

# 표준 라이브러리
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

# 외부 라이브러리
from fastapi import Response

# 프로젝트 모듈
from app.common.database import initialize_database
from app.users.application.dto import CreateUserCommand
from app.users.application.exceptions import UserNotFoundError
from app.users.application.services import UserService
from app.users.domain.entities import User
from app.users.domain.exceptions import DuplicateEmailError, InvalidUserError
from app.users.infrastructure.unit_of_work import SQLiteUserUnitOfWork
from app.users.presentation.router import create_user, get_user
from app.users.presentation.schemas import CreateUserRequest


class UserIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        """테스트용 임시 SQLite DB를 준비한다."""
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database_path = Path(self.directory.name) / "test.db"
        initialize_database(self.database_path)

    def make_service(self) -> UserService:
        """임시 DB를 사용하는 사용자 서비스를 생성한다."""
        return UserService(SQLiteUserUnitOfWork(self.database_path))

    def test_registered_user_is_persisted_and_normalized(self) -> None:
        """사용자 저장과 이름·이메일 정규화를 확인한다."""
        result = self.make_service().create_user(
            CreateUserCommand(name="  민성  ", email="  Minseong@Example.com  ")
        )
        stored = self.make_service().get_user(result.id)
        self.assertEqual(stored, result)
        self.assertEqual(stored.name, "민성")
        self.assertEqual(stored.email, "minseong@example.com")

    def test_user_routes_wrap_data_and_keep_the_location_header(self) -> None:
        """사용자 응답 형식과 Location 헤더를 확인한다."""
        response = Response()
        created = create_user(
            CreateUserRequest(name="민성", email="Minseong@Example.com"), self.make_service(), response,
        )
        fetched = get_user(created.data.id, self.make_service())
        self.assertEqual(response.headers["Location"], f"/api/v1/users/{created.data.id}")
        self.assertEqual(created, fetched)
        self.assertEqual(created.code, "SUCCESS")
        self.assertEqual(created.data.email, "minseong@example.com")
        self.assertEqual(set(created.model_dump()), {"code", "message", "data", "details"})

    def test_duplicate_email_does_not_replace_original_user(self) -> None:
        """중복 이메일 오류가 기존 사용자를 변경하지 않는지 확인한다."""
        service = self.make_service()
        original = service.create_user(CreateUserCommand("원본", "user@example.com"))
        with self.assertRaises(DuplicateEmailError):
            service.create_user(CreateUserCommand("중복", "USER@example.com"))
        self.assertEqual(service.get_user(original.id).name, "원본")
        other = service.create_user(CreateUserCommand("다음 사용자", "other@example.com"))
        self.assertEqual(service.get_user(other.id), other)

    def test_missing_user_raises_not_found(self) -> None:
        """없는 사용자 조회 시 오류를 확인한다."""
        with self.assertRaises(UserNotFoundError):
            self.make_service().get_user(uuid4())

    def test_invalid_user_is_not_saved(self) -> None:
        """유효하지 않은 사용자의 저장을 거부한다."""
        for name, email in [("   ", "user@example.com"), ("사용자", "invalid")]:
            with self.subTest(name=name, email=email):
                with self.assertRaises(InvalidUserError):
                    self.make_service().create_user(CreateUserCommand(name, email))

    def test_database_unique_constraint_prevents_duplicate_without_precheck(self) -> None:
        """DB 고유 제약이 이메일 중복을 차단하는지 확인한다."""
        self.make_service().create_user(CreateUserCommand("원본", "user@example.com"))
        with self.assertRaises(DuplicateEmailError):
            with SQLiteUserUnitOfWork(self.database_path) as uow:
                uow.users.add(User(name="중복", email="user@example.com"))
                uow.commit()

    def test_later_failure_rolls_back_earlier_insert(self) -> None:
        """후속 저장 실패 시 앞선 저장도 롤백하는지 확인한다."""
        first = User(name="첫 사용자", email="user@example.com")
        with self.assertRaises(DuplicateEmailError):
            with SQLiteUserUnitOfWork(self.database_path) as uow:
                uow.users.add(first)
                uow.users.add(User(name="중복", email="user@example.com"))
                uow.commit()
        with self.assertRaises(UserNotFoundError):
            self.make_service().get_user(first.id)

    def test_work_without_commit_is_rolled_back(self) -> None:
        """커밋하지 않은 작업의 롤백을 확인한다."""
        user = User(name="미완료", email="user@example.com")
        with SQLiteUserUnitOfWork(self.database_path) as uow:
            uow.users.add(user)
        with self.assertRaises(UserNotFoundError):
            self.make_service().get_user(user.id)


if __name__ == "__main__":
    unittest.main()
