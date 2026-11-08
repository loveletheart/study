"""중앙 오류 정의에서 Swagger 응답 예시와 코드 표를 생성한다."""

# 표준 라이브러리
from typing import Any

# 프로젝트 모듈
from app.common.errors.codes import ERROR_SPECS, ErrorCode
from app.common.errors.schemas import ErrorResponse


def error_responses(*codes: ErrorCode, include_validation: bool = True) -> dict[int | str, dict[str, Any]]:
    """Swagger 오류 응답과 예시 생성"""
    selected = [*codes, ErrorCode.COMMON_INTERNAL_ERROR]
    if include_validation:
        selected.append(ErrorCode.COMMON_INVALID_REQUEST)
    responses: dict[int | str, dict[str, Any]] = {}
    for code in dict.fromkeys(selected):
        spec = ERROR_SPECS[code]
        response = responses.setdefault(spec.status_code, {
            "model": ErrorResponse,
            "description": "",
            "content": {"application/json": {"examples": {}}},
        })
        response["description"] += f"- `{code.value}`: {spec.message}\n"
        response["content"]["application/json"]["examples"][code.value] = {
            "summary": spec.message,
            "value": ErrorResponse(code=code, message=spec.message).model_dump(mode="json"),
        }
    return responses


def error_code_table() -> str:
    """Swagger 오류 코드 표 생성"""
    rows = ["| 코드 | 기본 HTTP 상태 | 설명 |", "| --- | --- | --- |"]
    rows.extend(f"| `{code.value}` | {spec.status_code} | {spec.message} |" for code, spec in ERROR_SPECS.items())
    return "\n".join(rows)
