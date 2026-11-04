# FastAPI DDD 학습 프로젝트

업무별로 폴더를 나누고, 각 업무 내부를 presentation / application / domain / infrastructure 계층으로 구성합니다. 현재는 사용자 등록·단건 조회를 예시로 구현했습니다. 비밀번호·로그인·인증은 포함하지 않습니다.

## 실행

프로젝트 폴더의 PowerShell에서 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

가상환경을 활성화하지 않고도 실행할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

- Swagger: http://127.0.0.1:8000/docs
- 상태 확인: http://127.0.0.1:8000/health

## 설정과 DB

`.env`가 없어도 기본값으로 실행됩니다. 설정을 변경하려면 `.env.example`을 `.env`로 복사합니다.

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `STUDY_APP_NAME` | `Study API` | Swagger에 표시할 앱 이름 |
| `STUDY_DATABASE_PATH` | `study.db` | SQLite 파일 경로 |

실제 환경변수가 `.env` 값보다 우선합니다. 상대 DB 경로는 프로젝트 루트 기준입니다. 서버 시작 시 테이블이 없으면 생성하고, 사용자 데이터는 DB 파일에 저장합니다. DB 파일과 `.env`는 Git에서 제외합니다.

현재 추가 패키지 다운로드가 제한되어 Python 기본 `sqlite3` 드라이버를 사용합니다. `models.py`는 SQL 테이블 정의와 행 매핑을 담으며 SQLAlchemy ORM 모델은 아닙니다. ORM 도입 시 infrastructure의 모델·저장소·Unit of Work 및 common의 연결 설정을 교체하고 domain과 application의 계약을 유지할 수 있습니다. DB 테이블 구조 변경을 자동 반영하는 마이그레이션 도구는 아직 구성하지 않았습니다.

## 파일 역할

| 위치 | 역할 |
| --- | --- |
| `main.py` | FastAPI 생성, 시작 시 테이블 초기화, 라우터 등록 |
| `app/common/config.py` | 환경변수와 `.env` 설정 읽기 |
| `app/common/database.py` | DB 연결과 개발용 테이블 초기화 |
| `app/users/presentation/router.py` | HTTP 요청, Service 호출, 상태 코드·응답 반환 |
| `app/users/presentation/schemas.py` | Pydantic 요청·응답 형식 |
| `app/users/application/services.py` | 사용자 등록·조회 절차와 트랜잭션 범위 |
| `app/users/application/dto.py` | HTTP와 독립된 기능 입력·결과 데이터 |
| `app/users/application/exceptions.py` | 사용자를 찾지 못한 경우의 예외 |
| `app/users/application/unit_of_work.py` | 트랜잭션과 저장소에 접근하기 위한 추상 계약 |
| `app/users/domain/entities.py` | 사용자 객체, 이름·이메일 규칙 |
| `app/users/domain/repositories.py` | 사용자 저장·조회 인터페이스 |
| `app/users/domain/exceptions.py` | 잘못된 사용자 정보·이메일 중복 예외 |
| `app/users/infrastructure/models.py` | 사용자 테이블 SQL과 DB 행 매핑 |
| `app/users/infrastructure/repositories.py` | 파라미터 바인딩을 사용하는 실제 SQL 처리 |
| `app/users/infrastructure/unit_of_work.py` | 커밋, 롤백, 연결 종료 구현 |
| `app/users/bootstrap.py` | 실제 DB 구현체를 Service에 주입 |
| `tests/test_users.py` | 임시 SQLite DB를 사용하는 저장·중복·롤백 검증 |

## 요청 흐름과 의존성

1. Router는 요청 스키마를 입력 DTO로 변환하고 Service를 호출합니다.
2. Service는 Domain 객체를 만들어 업무 규칙을 검증합니다.
3. Service는 Unit of Work를 열고 Repository 인터페이스로 조회·저장합니다.
4. SQLite Repository가 실제 SQL을 실행합니다.
5. Service가 커밋한 뒤 결과 DTO를 반환하고 Router가 응답 스키마로 변환합니다.

Domain은 FastAPI·Pydantic·DB 구현을 import하지 않습니다. Application은 Repository·트랜잭션 계약에 의존하고, SQLite 구현은 bootstrap에서 연결합니다. Repository 내부에서는 커밋하지 않습니다. 예외가 발생하거나 커밋하지 않은 작업은 Unit of Work가 롤백하고 연결을 닫습니다.

## API 예시

Swagger에서 `POST /api/v1/users`를 실행합니다.

```json
{
  "name": "김민성",
  "email": "minseong@example.com"
}
```

| 요청 | 정상 결과 | 주요 오류 |
| --- | --- | --- |
| `POST /api/v1/users` | `201`, 생성된 UUID·이름·이메일 | 이메일 중복 `409`, 잘못된 입력 `422` |
| `GET /api/v1/users/{user_id}` | `200`, 사용자 정보 | 없는 사용자 `404`, 잘못된 UUID `422` |
| `GET /health` | `200`, `{"status": "ok"}` | 앱 응답 여부 확인용 |

생성 결과의 `id`를 조회 API에 입력합니다. 이름의 앞뒤 공백을 제거하고 이메일 전체를 소문자로 정규화합니다. 이메일은 기본 형식만 검증하며 실제 수신·소유 여부는 확인하지 않습니다. 사전 중복 조회와 DB UNIQUE 제약으로 중복 이메일을 방지합니다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

테스트마다 임시 DB를 만들고 종료 시 정리하므로 실제 `study.db`에 테스트 데이터를 남기지 않습니다.

## 다음 업무 추가

주문 기능을 추가한다면 `app/orders/` 아래 같은 4개 계층과 `bootstrap.py`를 배치하고 `main.py`에서 라우터를 등록합니다. 공통 폴더에는 환경 설정·DB 연결처럼 여러 업무가 사용하는 기술 기반만 둡니다.
