class InvalidUserError(ValueError):
    """사용자 정보가 업무 규칙을 만족하지 않는다."""


class DuplicateEmailError(Exception):
    """이미 등록된 이메일이다."""
