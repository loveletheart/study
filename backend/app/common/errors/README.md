# 공통 오류 처리

모든 API는 `common/responses.py`의 `ApiResponse` 형식을 사용합니다. 성공 시 `code`는 `SUCCESS`이고 결과는 `data`에 담습니다. 실패 시 `data`는 `null`이며 기존 HTTP 상태와 오류 코드를 사용합니다.

```json
{
  "code": "WEATHER_TIMEOUT",
  "message": "날씨 제공 서비스의 응답 시간이 초과되었습니다.",
  "data": null,
  "details": []
}
```

요청 입력 검증 실패는 HTTP 422와 `COMMON_INVALID_REQUEST`로 반환합니다.

```json
{
  "code": "COMMON_INVALID_REQUEST",
  "message": "요청 입력값을 확인해 주세요.",
  "data": null,
  "details": [
    {
      "field": "query.latitude",
      "message": "Input should be less than or equal to 90",
      "type": "less_than_equal"
    }
  ]
}
```

`details`에는 실패한 필드의 위치·검증 설명·오류 종류만 포함합니다. 원본 요청 본문, 입력값, 내부 예외 객체는 반환하지 않습니다. 검증 상세 메시지는 Pydantic의 설명을 사용하며 최상위 안내 메시지는 한국어입니다.

## 파일 역할

| 파일 | 역할 |
| --- | --- |
| `codes.py` | ErrorCode와 기본 HTTP 상태·한국어 메시지의 단일 관리 지점 |
| `exceptions.py` | FastAPI에 의존하지 않는 공통 AppError |
| `schemas.py` | ApiResponse를 상속하는 오류 응답 모델 |
| `handlers.py` | 업무·요청 검증·HTTP·미처리 오류를 JSON으로 변환 |
| `openapi.py` | 오류 코드 정의로 Swagger 응답 예시와 전체 코드 표 생성 |

전체 코드 목록은 `codes.py` 또는 Swagger 첫 화면에서 확인합니다. `COMMON_HTTP_ERROR`는 등록되지 않은 일반 HTTP 예외에 사용하고 원래 HTTP 상태와 헤더를 유지합니다. 코드 표의 HTTP 상태는 기본값입니다. 예기치 않은 서버 오류는 상세 내용을 서버 로그에 남기고 클라이언트에는 일반적인 500 메시지만 반환합니다.

## 새 오류 추가

1. `codes.py`의 `ErrorCode`와 `ERROR_SPECS`에 코드·상태·기본 메시지를 추가합니다.
2. 해당 업무의 예외를 `AppError`에서 상속하고 `error_code`를 지정합니다.
3. 업무 코드에서 그 예외를 발생시킵니다. 기본 메시지는 인수 없이 사용하며 업무 규칙을 설명할 공개 메시지가 필요한 경우에만 문자열을 전달합니다.
4. 라우터의 `error_responses(...)`에 해당 코드를 추가합니다.

```python
class WeatherProviderTimeoutError(AppError):
    error_code = ErrorCode.WEATHER_TIMEOUT

# 업무 코드: HTTP 상태나 JSON 형식을 알 필요가 없습니다.
raise WeatherProviderTimeoutError()

# 라우터: 해당 API가 반환할 오류를 Swagger에 문서화합니다.
responses = error_responses(ErrorCode.WEATHER_TIMEOUT)
```

공통 핸들러는 `backend/main.py`에서 한 번 등록합니다. 새 AppError 하위 예외를 추가할 때 핸들러를 수정할 필요가 없습니다. Domain과 Application에는 FastAPI HTTPException이나 JSONResponse를 넣지 않습니다.

## 메서드 설명 확인

- Swagger에는 짧은 API 설명, 요청·응답 필드와 오류 예시가 표시됩니다.
- 같은 HTTP 상태에 여러 업무 오류가 있으면 Example Value의 예시 선택 목록으로 구분합니다. 예: 503의 WEATHER_UNAVAILABLE / WEATHER_RATE_LIMITED.
- 내부 메서드의 역할은 메서드 바로 위 한 줄 주석으로 확인합니다.
