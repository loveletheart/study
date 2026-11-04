"""FastAPI와 DB 라이브러리에 의존하지 않는 사용자 업무 객체."""

import re
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from app.users.domain.exceptions import InvalidUserError


@dataclass(frozen=True)
class User:
    name: str
    email: str
    id: UUID = field(default_factory=uuid4)

    # 이름·이메일 검증 및 정규화
    def __post_init__(self) -> None:
        name = self.name.strip()
        # 이 예제에서는 이메일 전체를 대소문자 구분 없이 관리한다.
        email = self.email.strip().casefold()
        if not 1 <= len(name) <= 100:
            raise InvalidUserError("이름은 1~100자여야 합니다.")
        # 학습 예제의 기본 형식 검증이며 이메일 소유 여부 검증은 별도다.
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise InvalidUserError("올바른 이메일 형식을 입력해 주세요.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "email", email)
