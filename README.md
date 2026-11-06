# FastAPI와 DDD 학습 프로젝트

업무별로 폴더를 나누고, 각 업무 내부를 presentation / application / domain / infrastructure 계층으로 구성합니다. 현재는 날씨 조회, 날씨 기반 옷차림 추천과 사용자 등록·단건 조회 예시를 구현했습니다. 비밀번호·로그인·인증은 포함하지 않습니다.

## 실행

Windows에 Python 3.11 이상이 설치되어 있어야 합니다. 새로 체크아웃한 경우에도 프로젝트 폴더의 PowerShell에서 아래 명령 하나로 실행합니다.

```powershell
.\run.cmd
```

실행 순서는 다음과 같습니다. 어느 단계든 실패하면 서버를 시작하지 않습니다.

1. `.venv`가 없으면 생성합니다. 활성화 스크립트가 누락된 가상환경도 복구합니다.
2. `.venv`를 활성화하고 프로젝트 가상환경의 Python인지 확인합니다.
3. `.venv`의 pip로 `backend/requirements.txt` 의존성을 확인·설치합니다.
4. `.venv`의 Python으로 Uvicorn 서버를 실행합니다.

이미 생성된 가상환경은 재사용합니다. 최초 의존성 설치에는 패키지 다운로드를 위한 인터넷 연결이 필요합니다. `run.cmd`는 실행하는 PowerShell 프로세스에만 스크립트 실행 정책을 지정합니다.

VS Code에서는 **Ctrl+Shift+B**로 같은 실행 절차를 사용할 수 있습니다. **F5 → FastAPI (.venv)**는 환경 준비 작업을 먼저 실행한 뒤 가상환경 Python으로 디버깅합니다. `backend/main.py`의 **Run Python File** 버튼도 동일한 실행 스크립트를 호출합니다. F5 디버깅에는 VS Code의 Python / Python Debugger 확장이 필요합니다.

서버를 띄우지 않고 환경만 준비하거나 포트를 변경할 수도 있습니다.

```powershell
.\run.cmd -SetupOnly
.\run.cmd -Port 8001
```

- Swagger: http://127.0.0.1:8000/docs
- 상태 확인: http://127.0.0.1:8000/health

## 날씨 API

Python 코드는 `backend/`에 있고, `.venv`, `.env`, 실행 스크립트와 기존 `study.db`는 프로젝트 루트에 있습니다. 프론트엔드는 이후 Vue로 연결합니다.

| API | 역할 |
| --- | --- |
| `GET /api/v1/weather/locations?query=서울` | 국내 지역 검색 |
| `GET /api/v1/weather/today?latitude=37.5665&longitude=126.978` | 현재 날씨, 오늘 예보, 시간별 정보와 요약 |
| `GET /api/v1/weather/weekly?latitude=37.5665&longitude=126.978` | 오늘부터 7일 예보 |

지역 검색에서 선택한 위도·경도를 날씨 API에 전달합니다. 모든 예보 날짜는 한국 시간 기준입니다. 실제 날씨는 Open-Meteo 공개 API에서 가져오며 서버 시작이나 조회 실패 시 임의의 샘플 날씨를 반환하지 않습니다.

응답 필드·오류 코드·캐시 동작은 [날씨 기능 문서](backend/app/weather/README.md)에 정리했습니다.

## 옷차림 추천 API

| API | 역할 |
| --- | --- |
| `GET /api/v1/outfits/today?latitude=37.5665&longitude=126.978` | 오늘의 베스트·워스트 옷차림과 추천 이유 |
| `GET /api/v1/outfits/weekly?latitude=37.5665&longitude=126.978` | 오늘부터 7일 옷차림과 중복 없는 주간 준비 의류 |
| `GET /api/v1/outfits/regions/{location_id}/today` | 공식 시군구 공통 오늘 추천과 동적 개인화 |
| `GET /api/v1/outfits/regions/{location_id}/weekly` | 선택한 동네의 공통 주간 추천과 개인별 준비 의류 |

기존 날씨 조회와 캐시를 재사용하고 날씨를 로컬 Ollama에 전달해 옷차림을 생성합니다. 설정을 켜면 로컬 실패 시 Gemini API로 자동 전환합니다. 사용 모델은 직접 설정하며 이미지와 인기 순위는 후속 작업입니다. 연결 방법과 응답 형식은 [옷차림 기능 문서](backend/app/outfits/README.md)를 참고하세요.

로컬 추천은 Ollama 서버와 모델을 별도로 준비하고 `.env`의 `STUDY_LLM_MODEL`에 `ollama list`에 표시된 모델명을 입력하세요. 자동 전환을 끈 상태에서 모델이 미설정이면 `OUTFIT_LLM_NOT_CONFIGURED`(503)를 반환합니다. 서버가 모델을 자동 설치하거나 다운로드하지 않습니다.

옷차림 추천은 지역·오늘/주간별로 SQLite에 저장합니다. 최근 24시간 안에 조회한 지역은 서버 실행 중 기본 1시간 간격으로 날씨를 확인하고 모델 입력값이 바뀐 경우에만 추천을 다시 생성합니다. 갱신 중인 조회에는 저장된 결과를 제공합니다. 처음 조회하는 지역·종류는 생성 시간이 필요합니다. 저장 결과는 재시작 후에도 재사용하지만 한국 날짜가 바뀌거나 마지막 정상 확인 후 갱신 주기의 3배(기본 3시간)를 넘으면 새로 생성합니다. `fetched_at`은 날씨 조회 시각, `generated_at`은 실제 기본 추천 생성 시각입니다. 자세한 갱신 정책은 [옷차림 기능 문서](backend/app/outfits/README.md#추천-저장과-시간별-갱신)를 참고하세요.

동네 공유 API는 먼저 `/api/v1/weather/locations`로 지역을 검색한 뒤 응답의 `id`를 `location_id`로 전달합니다. 검색 좌표를 브이월드의 공식 시군구 경계에 조회하고, 같은 `sig_cd`에 속한 위치는 고정 대표점의 기본 추천을 공유합니다. 이름이나 좌표 반올림으로 구역을 추정하지 않습니다. 이를 위해 로컬 `.env`에 `VWORLD_API_KEY`와 발급 시 등록한 도메인인 `STUDY_VWORLD_DOMAIN`을 설정합니다. 키가 없고 저장된 판정도 없으면 `WEATHER_REGION_NOT_CONFIGURED`(503)를 반환합니다.

`cold_sensitivity=normal|cold|warm`, `style=default|casual|formal`, `activity=daily|outdoor|active` 옵션은 기본 추천과 별개로 LLM이 실제 의류와 자연어 설명을 생성하며, 같은 시군구·기본 버전·조건 조합은 재사용합니다. 최근 24시간의 조건을 공통 갱신 예정 10분 전부터 준비합니다. 기본 추천이 바뀌면 새 버전을 먼저 준비하고 해당 버전에 맞춰 개인화를 생성합니다. 최초 조합은 생성 시간이 필요하며 10분 안에 완료되는 것을 보장하지 않습니다.

Gemini 자동 전환은 기본적으로 꺼져 있습니다. 사용하려면 `.env`에 다음 값을 설정하고 서버를 재시작합니다. API 키는 Git에 올리지 않습니다.

```dotenv
STUDY_LLM_CLOUD_FALLBACK_ENABLED=true
GEMINI_API_KEY=발급받은_API_키
STUDY_GEMINI_MODEL=gemini-flash-latest
```

클라우드는 Google GenAI 공식 Python SDK와 JSON 스키마 출력을 사용합니다. 자동 전환을 켜도 로컬 대기 제한은 `STUDY_LLM_TIMEOUT_SECONDS`(기본 180초)를 유지하며, Gemini는 기본 60초입니다. 로컬 대기를 더 짧게 제한하려는 경우에만 `STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS`를 지정하세요. 로컬 모델 미설정도 전환 대상이며, 로컬 성공 시 Gemini 키 확인과 호출을 건너뜁니다. 응답의 `data.engine`에서 실제 제공사·모델·전환 여부를 확인합니다.

## API 설명과 공통 오류

Swagger 첫 화면에는 전체 오류 코드 표가 표시됩니다. 각 API를 펼치면 한국어 기능 설명, 입력 조건, 응답 필드와 오류 코드별 예시를 확인할 수 있습니다. 내부 메서드는 함수 본문 첫 줄의 짧은 docstring으로 역할을 표시합니다.

모든 API는 `code`, `message`, `data`, `details` 형식을 사용합니다. 성공 결과는 기존 최상위 필드에서 `data` 안으로 이동했습니다. HTTP 상태 코드와 API 경로는 동일합니다.

```json
{
  "code": "SUCCESS",
  "message": "요청이 성공했습니다.",
  "data": {"status": "ok"},
  "details": []
}
```

실패 시 `data`는 `null`이며, 입력 검증 오류는 `details`에 담습니다.

```json
{
  "code": "WEATHER_TIMEOUT",
  "message": "날씨 제공 서비스의 응답 시간이 초과되었습니다.",
  "data": null,
  "details": []
}
```

오류 코드·기본 HTTP 상태·기본 메시지는 `backend/app/common/errors/codes.py`에서 관리합니다. 새 오류를 추가하는 방법과 검증 오류 응답은 [공통 오류 문서](backend/app/common/errors/README.md)를 참고하세요.

## 설정과 DB

`.env`가 없어도 기본값으로 실행됩니다. 설정을 변경하려면 프로젝트 루트에 `.env`를 만들고 아래 설정값을 입력합니다.

| 설정 | 기본값 | 의미 |
| --- | --- | --- |
| `STUDY_APP_NAME` | `Study API` | Swagger에 표시할 앱 이름 |
| `STUDY_DATABASE_PATH` | `study.db` | SQLite 파일 경로 |
| `STUDY_WEATHER_TIMEOUT_SECONDS` | `10` | 외부 날씨 API 제한 시간(0.1~30초) |
| `STUDY_WEATHER_CACHE_TTL_SECONDS` | `600` | 날씨 캐시 유지 시간(0~3600초, 0은 캐시 해제) |
| `STUDY_LLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama 서버의 기본 주소 |
| `STUDY_LLM_MODEL` | 빈 문자열 | 직접 준비한 로컬 모델명 |
| `STUDY_LLM_TIMEOUT_SECONDS` | `180` | 추론 응답 대기 시간(1~600초) |
| `STUDY_LLM_CONTEXT_SIZE` | `16384` | 요청 문맥 길이(2048~131072 정수). 모델·메모리에 맞춰 조절 |
| `STUDY_LLM_CLOUD_FALLBACK_ENABLED` | `false` | `true`일 때 로컬 실패 후 Gemini 한 번 호출 |
| `STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS` | 미설정 | 생략·빈 값이면 일반 로컬 대기 제한 유지. 지정하면 두 제한 중 작은 값 적용(1~600초) |
| `STUDY_OUTFIT_REFRESH_SECONDS` | `3600` | 조회한 지역의 추천 갱신 간격(60~86400초). 서버 실행 중 동작 |
| `STUDY_OUTFIT_CACHE_MAX_ENTRIES` | `4096` | 공통 추천 보관 조합 수(1~100000). 지역·오늘/주간·모델 설정 조합 기준 |
| `VWORLD_API_KEY` | 빈 문자열 | 브이월드 시군구 공식 경계 조회 키. 로컬 설정에만 저장 |
| `STUDY_VWORLD_DOMAIN` | 빈 문자열 | 브이월드 키 발급 시 등록한 이용 도메인. 예: `http://localhost:8000` |
| `GEMINI_API_KEY` | 빈 문자열 | Gemini API 키. 클라우드 전환 시 필요 |
| `STUDY_GEMINI_MODEL` | 빈 문자열 | JSON 스키마 출력을 지원하는 Gemini 모델명. 예: `gemini-flash-latest` |
| `STUDY_GEMINI_TIMEOUT_SECONDS` | `60` | Gemini 응답 대기 제한(1~300초) |
| `STUDY_GEMINI_MAX_OUTPUT_TOKENS` | `8192` | Gemini 출력 토큰 상한(128~32768 정수). 모델에 따라 내부 추론도 한도에 포함될 수 있음 |

설정 우선순위는 프로젝트 루트의 `.env` → 환경변수 → 코드 기본값입니다. `.env`에 작성한 값은 같은 이름의 환경변수보다 우선합니다. 파일 수정 후 서버를 재시작하면 반영됩니다. VS Code의 `python.terminal.useEnvFile`은 `false`로 두어도 코드가 직접 `.env`를 읽습니다. 상대 DB 경로는 프로젝트 루트 기준입니다. 서버 시작 시 테이블이 없으면 생성하고, 사용자 데이터는 DB 파일에 저장합니다. DB 파일과 `.env`는 Git에서 제외합니다.

현재 추가 패키지 다운로드가 제한되어 Python 기본 `sqlite3` 드라이버를 사용합니다. `models.py`는 SQL 테이블 정의와 행 매핑을 담으며 SQLAlchemy ORM 모델은 아닙니다. ORM 도입 시 infrastructure의 모델·저장소·Unit of Work 및 common의 연결 설정을 교체하고 domain과 application의 계약을 유지할 수 있습니다. DB 테이블 구조 변경을 자동 반영하는 마이그레이션 도구는 아직 구성하지 않았습니다.

## 파일 역할

| 위치 | 역할 |
| --- | --- |
| `backend/main.py` | FastAPI 생성, 시작 시 테이블 초기화, 라우터 등록 |
| `run.cmd` / `run.ps1` | 가상환경 생성·활성화, 의존성 설치, 서버·테스트 실행 |
| `.vscode/tasks.json` / `.vscode/launch.json` | 환경 준비를 먼저 수행하는 실행·디버깅 설정 |
| `backend/app/common/config.py` | 환경변수와 `.env` 설정 읽기 |
| `backend/app/common/database.py` | DB 연결과 개발용 테이블 초기화 |
| `backend/app/common/responses.py` | 모든 API의 공통 응답 형식 |
| `backend/app/common/errors/` | 공통 오류 코드·응답 모델·예외 핸들러·Swagger 오류 문서 |
| `backend/app/outfits/` | 날씨 기반 LLM 추천·Gemini 자동 전환·오늘/주간 조회·응답 검증 |
| `backend/app/users/presentation/router.py` | HTTP 요청, Service 호출, 상태 코드·응답 반환 |
| `backend/app/users/presentation/schemas.py` | Pydantic 요청·응답 형식 |
| `backend/app/users/application/services.py` | 사용자 등록·조회 절차와 트랜잭션 범위 |
| `backend/app/users/application/dto.py` | HTTP와 독립된 기능 입력·결과 데이터 |
| `backend/app/users/application/exceptions.py` | 사용자를 찾지 못한 경우의 예외 |
| `backend/app/users/application/unit_of_work.py` | 트랜잭션과 저장소에 접근하기 위한 추상 계약 |
| `backend/app/users/domain/entities.py` | 사용자 객체, 이름·이메일 규칙 |
| `backend/app/users/domain/repositories.py` | 사용자 저장·조회 인터페이스 |
| `backend/app/users/domain/exceptions.py` | 잘못된 사용자 정보·이메일 중복 예외 |
| `backend/app/users/infrastructure/models.py` | 사용자 테이블 SQL과 DB 행 매핑 |
| `backend/app/users/infrastructure/repositories.py` | 파라미터 바인딩을 사용하는 실제 SQL 처리 |
| `backend/app/users/infrastructure/unit_of_work.py` | 커밋, 롤백, 연결 종료 구현 |
| `backend/app/users/bootstrap.py` | 실제 DB 구현체를 Service에 주입 |
| `backend/tests/test_users.py` | 임시 SQLite DB를 사용하는 저장·중복·롤백 검증 |
| `backend/tests/test_startup.py` | 새 가상환경 생성, 재사용, 활성화 스크립트 복구, 설치 실패 시 중단 검증 |

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
| `GET /health` | `200`, `data.status`가 `ok` | 앱 응답 여부 확인용 |

생성 결과의 `data.id`를 조회 API에 입력합니다. 이름의 앞뒤 공백을 제거하고 이메일 전체를 소문자로 정규화합니다. 이메일은 기본 형식만 검증하며 실제 수신·소유 여부는 확인하지 않습니다. 사전 중복 조회와 DB UNIQUE 제약으로 중복 이메일을 방지합니다.

## 검증

```powershell
.\run.cmd -Test
```

테스트마다 임시 DB를 만들고 종료 시 정리하므로 실제 `study.db`에 테스트 데이터를 남기지 않습니다.

## 다음 업무 추가

새 업무는 `backend/app/` 아래 4개 계층과 `bootstrap.py`를 배치하고 `backend/main.py`에서 라우터를 등록합니다. 옷차림 추천의 외부 날씨 연결처럼 다른 업무의 구현을 사용하는 부분은 infrastructure에 둡니다. 공통 폴더에는 여러 업무가 사용하는 환경 설정·DB 연결·응답 형식을 둡니다.
