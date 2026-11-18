# FastAPI와 DDD 학습 프로젝트

**온도**는 날씨를 조회하고 오늘과 주간의 옷차림을 추천하는 서비스입니다. 계정에 지역과 취향을 저장하고, 추천 결과를 신고하거나 수정할 수 있습니다.

Python 백엔드는 `backend/`, Vue 프론트엔드는 `frontend/`에 있습니다. 백엔드는 사용자, 날씨, 옷차림 업무를 구분하고 각 업무를 `presentation`, `application`, `domain`, `infrastructure` 계층으로 구성합니다.

## 프로젝트 문서

[온도 프로젝트 명세](docs/project-spec.md)에서 기능, API, 데이터 구조, 운영 정책과 설계를 확인할 수 있습니다. GitHub에서 로그인 없이 읽을 수 있습니다.

## 기술 선택 이유

### FastAPI를 선택한 이유

Flask로 개발할 때 비동기 뷰를 쓰기 위해 의존성을 추가하고, Swagger UI도 별도로 구성해야 했습니다. 이번 프로젝트에서는 Vue 화면과 백엔드를 나눠 개발하면서 날씨 조회와 로컬 Ollama를 연결한 추천 API를 Swagger에서 바로 확인하고 싶었습니다. 그래서 비동기 라우트와 Swagger UI 자동 생성을 기본으로 제공하는 FastAPI를 선택했습니다. 

### Vue를 선택한 이유

 Node.js 환경에서 화면을 간단하게 구성하려고 했습니다. 개발을 진행하면서 지역을 검색하고 취향을 입력한 뒤 옷차림을 확인하는 과정을 브라우저에서 직접 테스트할 필요가 생겼습니다. 그래서 지역 검색, 취향 입력, 추천 카드를 컴포넌트로 나누고 실제 사용 흐름을 화면에서 검증할 수 있도록 Vue를 선택했습니다. [프론트엔드 개발과 테스트](frontend/README.md)

### Redis를 선택한 이유

같은 지역의 예보를 여러 사용자가 반복해서 조회하고, 시군구 옷차림 추천도 대표 좌표의 예보를 사용합니다. Redis를 연결하면 날씨 화면과 추천 갱신이 같은 예보를 공유하고, FastAPI를 재시작한 뒤에도 Redis에 남아 있는 데이터를 읽을 수 있습니다. 같은 좌표의 갱신 요청도 한 번으로 합쳐 Open-Meteo 호출을 줄입니다.

예보는 기본 1시간 동안 최신으로 보고 최대 3시간 보관합니다. 제공사에 일시 장애가 생기면 같은 한국 날짜의 마지막 정상 예보와 실제 조회 시각을 화면에 표시합니다. 계정과 옷차림 추천 결과는 SQLite에 저장합니다.

## 실행

Windows에 Python 3.11 이상과 Node.js 20.19 이상(20.x) 또는 22.12 이상이 설치되어 있어야 합니다. 새로 체크아웃한 경우에도 프로젝트 폴더의 PowerShell에서 아래 명령 하나로 실행합니다.

```powershell
.\run.cmd
```

실행 순서는 다음과 같습니다. 어느 단계든 실패하면 서버를 시작하지 않습니다.

1. `.venv`가 없으면 생성합니다. 활성화 스크립트가 누락된 가상환경도 복구합니다.
2. `.venv`를 활성화하고 프로젝트 가상환경의 Python인지 확인합니다.
3. `.venv`의 pip로 `backend/requirements.txt` 의존성을 확인·설치합니다.
4. 프런트엔드 의존성이 없거나 패키지 설정이 바뀌면 `npm ci`로 설치합니다. 화면 빌드가 없거나 입력 파일이 바뀌면 `npm run build`로 갱신합니다.
5. `.venv`의 Python으로 Uvicorn 서버를 실행합니다.

이미 생성된 가상환경은 재사용합니다. 최초 의존성 설치에는 패키지 다운로드를 위한 인터넷 연결이 필요합니다. `run.cmd`는 실행하는 PowerShell 프로세스에만 스크립트 실행 정책을 지정합니다.

VS Code에서는 **Ctrl+Shift+B**로 같은 실행 절차를 사용할 수 있습니다. **F5 → FastAPI (.venv)**는 환경 준비 작업을 먼저 실행한 뒤 가상환경 Python으로 디버깅합니다. `backend/main.py`의 **Run Python File** 버튼도 동일한 실행 스크립트를 호출합니다. F5 디버깅에는 VS Code의 Python / Python Debugger 확장이 필요합니다.

서버를 띄우지 않고 환경만 준비하거나 포트를 변경할 수도 있습니다.

```powershell
.\run.cmd -SetupOnly
.\run.cmd -Port 8001
```

브랜치를 바꾼 뒤 VS Code에서 `redis` 같은 패키지를 찾을 수 없다는 경고가 나오면 루트에서 `.\run.cmd -SetupOnly`를 실행해 `.venv`의 백엔드 의존성을 갱신하세요. 설치 후에도 경고가 남으면 **Python: Select Interpreter**에서 `.venv\Scripts\python.exe`를 선택하세요.

- [Swagger](http://127.0.0.1:8000/docs)
- [웹 화면](http://127.0.0.1:8000/app/)
- [서버 상태 확인](http://127.0.0.1:8000/health)

## 프론트엔드 MVP

현재·시간별 날씨를 확인하고 오늘과 주간의 베스트·워스트 옷차림을 비교할 수 있습니다. 저장된 지역이 없으면 서울특별시 중구를 표시합니다. 둘러보기 설정은 브라우저에 저장하고, 로그인한 사용자는 지역·체감 온도·스타일·활동·선호 의류·피할 의류를 계정에 저장할 수 있습니다.

화면을 수정하면서 변경 사항을 바로 보려면 백엔드를 실행한 상태에서 별도 터미널로 아래 명령을 실행합니다.

```powershell
cd frontend
npm run dev
```

[프론트엔드 개발 화면](http://127.0.0.1:5173/app/)

[프론트엔드 실행 안내](frontend/README.md)

회원가입은 `/app/#signup`, 로그인은 `/app/#login`, 추천 프로필은 `/app/#profile`에서 제공합니다. 회원가입 뒤 프로필 설정으로 이동하며 언제든 나중에 설정할 수 있습니다. 계정 저장·인증 API와 기존 사용자 데이터의 호환 범위는 [사용자 기능 문서](backend/app/users/README.md)를 확인하세요.

## API 라우터

`backend/main.py`에서 사용자, 날씨, 옷차림 라우터를 `/api/v1` 아래에 등록합니다. 피드백 경로는 옷차림 라우터에 포함됩니다. 전체 요청·응답 명세는 [Swagger](http://127.0.0.1:8000/docs)에서 확인할 수 있습니다.

### 사용자와 인증

| API | 역할 |
| --- | --- |
| `POST /api/v1/users/auth/register` | 닉네임·이메일·비밀번호로 가입하고 세션 쿠키 발급 |
| `POST /api/v1/users/auth/login` | 이메일·비밀번호를 확인하고 현재 브라우저의 이전 세션 교체 |
| `POST /api/v1/users/auth/logout` | 현재 세션을 폐기하고 쿠키 삭제 |
| `GET /api/v1/users/me` | 로그인한 본인의 계정과 추천 프로필 조회 |
| `PUT /api/v1/users/me/profile` | 본인의 닉네임·지역·추천 취향 저장 |
| `POST /api/v1/users` | 이름과 이메일로 사용자 레코드를 생성하는 DDD 실습 API |
| `GET /api/v1/users/{user_id}` | 로그인한 본인의 사용자 정보 조회 |

세션은 로그인 후 **최대 1일(24시간)** 유지됩니다. 인증 요청이 30분 동안 없으면 먼저 만료되며, 화면은 다음 인증 확인에서 다시 로그인하도록 안내합니다. 세션 쿠키에는 `HttpOnly`와 `SameSite=Lax`가 적용되고, HTTPS에서는 `Secure`가 추가됩니다. 비밀번호는 개별 무작위 솔트를 사용해 scrypt로 해시한 뒤 SQLite의 `user_credentials.password_hash`에 저장합니다. [사용자 기능 문서](backend/app/users/README.md)

인증·프로필·피드백 변경 요청을 직접 보낼 때는 `X-Ondo-Request: 1` 헤더를 포함합니다. 보호 API에는 로그인 응답에서 받은 세션 쿠키도 함께 보냅니다.

### 날씨

| API | 역할 |
| --- | --- |
| `GET /api/v1/weather/locations?query=서울` | 국내 지역 포함 검색. `limit`·`offset`으로 전체 결과 페이지 조회 |
| `GET /api/v1/weather/today?latitude=37.5665&longitude=126.978` | 현재 날씨, 오늘 예보, 시간별 정보와 요약 |
| `GET /api/v1/weather/weekly?latitude=37.5665&longitude=126.978` | 오늘부터 7일 예보 |

지역 검색에서 선택한 위도·경도를 날씨 API에 전달합니다. 모든 예보 날짜는 한국 시간 기준입니다. 실제 날씨는 Open-Meteo 공개 API에서 가져오며 서버 시작이나 조회 실패 시 임의의 샘플 날씨를 반환하지 않습니다.

응답 필드·오류 코드·캐시 동작은 [날씨 기능 문서](backend/app/weather/README.md)에 정리했습니다.

### 옷차림 추천

| API | 역할 |
| --- | --- |
| `GET /api/v1/outfits/today?latitude=37.5665&longitude=126.978` | 오늘의 베스트·워스트 옷차림과 추천 이유 |
| `GET /api/v1/outfits/weekly?latitude=37.5665&longitude=126.978` | 최근 새벽 배치 기준 7일 옷차림과 주간 준비 의류 |
| `GET /api/v1/outfits/regions/{location_id}/today` | 공식 시군구 공통 오늘 추천과 동적 개인화 |
| `GET /api/v1/outfits/regions/{location_id}/weekly` | 선택한 동네의 공통 주간 추천과 개인별 준비 의류 |

기존 날씨 조회와 캐시를 재사용하고 날씨를 로컬 Ollama에 전달해 옷차림을 생성합니다. 설정을 켜면 로컬 실패 시 Gemini API로 자동 전환합니다. 사용 모델은 직접 설정하며 이미지와 인기 순위는 후속 작업입니다. 연결 방법과 응답 형식은 [옷차림 기능 문서](backend/app/outfits/README.md)를 참고하세요.

로컬 추천은 Ollama 서버와 모델을 별도로 준비하고 `.env`의 `STUDY_LLM_MODEL`에 `ollama list`에 표시된 모델명을 입력하세요. 자동 전환을 끈 상태에서 모델이 미설정이면 `OUTFIT_LLM_NOT_CONFIGURED`(503)를 반환합니다. 서버가 모델을 자동 설치하거나 다운로드하지 않습니다.

옷차림 추천은 지역·오늘/주간별로 SQLite에 저장합니다. 오늘은 최근 조회 지역의 날씨를 매시간 확인하고 모델 입력값이 바뀐 경우에만 재생성합니다. 로컬 모델의 오늘 문맥은 기본 4096토큰이며, 최초 조회·한국 날짜 변경·정상 확인 후 3시간 초과 시 생성이 필요합니다. 주간은 매일 한국 시간 새벽 1시 배치에서만 생성하고 조회에서는 모델을 호출하지 않습니다. 준비 전에는 `OUTFIT_WEEKLY_NOT_READY`(503)를 반환합니다. 최근 배치 결과는 기본 최대 48시간 보관하며 `forecast_start_date`로 예보 기준 날짜를 명시합니다. `fetched_at`은 사용한 날씨 조회 시각, `generated_at`은 기본 추천 생성 시각입니다. 자세한 정책은 [옷차림 기능 문서](backend/app/outfits/README.md#추천-저장과-시간별-갱신)를 참고하세요.

동네 공유 API는 먼저 `/api/v1/weather/locations`로 지역을 검색한 뒤 응답의 `id`를 `location_id`로 전달합니다. 검색 좌표를 브이월드의 공식 시군구 경계에 조회하고, 같은 `sig_cd`에 속한 위치는 고정 대표점의 기본 추천을 공유합니다. 이름이나 좌표 반올림으로 구역을 추정하지 않습니다. 이를 위해 로컬 `.env`에 `VWORLD_API_KEY`와 발급 시 등록한 도메인인 `STUDY_VWORLD_DOMAIN`을 설정합니다. 키가 없고 저장된 판정도 없으면 `WEATHER_REGION_NOT_CONFIGURED`(503)를 반환합니다.

`cold_sensitivity=normal|cold|warm`, `style=default|casual|formal`, `activity=daily|outdoor|active` 옵션은 기본 추천과 별개로 LLM이 의류와 자연어 설명을 생성하며 같은 조건 조합은 재사용합니다. 오늘의 최근 조건은 공통 갱신 10분 전부터 준비하고 최초 조합은 요청 시 생성합니다. 주간의 새 조건은 등록만 하고 다음 새벽 배치에서 생성합니다. 주간 배치는 한국 시간 01:00부터 당일 작업을 확인하고, 서버가 늦게 켜지거나 배치가 중단되면 남은 작업을 이어서 처리합니다.

Gemini 자동 전환은 기본적으로 꺼져 있습니다. 사용하려면 `.env`에 다음 값을 설정하고 서버를 재시작합니다. API 키는 Git에 올리지 않습니다.

```dotenv
STUDY_LLM_CLOUD_FALLBACK_ENABLED=true
GEMINI_API_KEY=발급받은_API_키
STUDY_GEMINI_MODEL=gemini-flash-latest
```

클라우드는 Google GenAI 공식 Python SDK와 JSON 스키마 출력을 사용합니다. 자동 전환을 켜면 Ollama 요청당 기본 20초를 기다립니다. 시간 초과 시 한 번 다시 요청하고, 다시 실패하면 Gemini를 호출합니다. `STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS`를 설정하면 해당 값과 `STUDY_LLM_TIMEOUT_SECONDS` 중 작은 값을 적용합니다. Gemini는 기본 60초입니다. 로컬 모델 미설정도 전환 대상이며, 응답의 `data.engine`에서 실제 제공사·모델·전환 여부를 확인합니다.

### 추천 피드백과 학습자료

| API | 역할 |
| --- | --- |
| `POST /api/v1/outfit-feedback` | 추천 답변 신고와 수정안 초안 등록 |
| `GET /api/v1/outfit-feedback` | 내 신고와 수정안 목록 조회 |
| `GET /api/v1/outfit-feedback/{identifier}` | 내 신고의 원본 답변, 날씨, 수정안과 검증 결과 조회 |
| `PUT /api/v1/outfit-feedback/{identifier}` | 내 수정안 초안 편집 |
| `POST /api/v1/outfit-feedback/{identifier}/approve` | 검증을 통과한 내 수정안 승인 |
| `POST /api/v1/outfit-feedback/{identifier}/reject` | 내 수정안 거절 |
| `GET /api/v1/outfit-feedback/export` | 본인이 승인한 수정안을 학습자료 형식으로 조회 |

추천 화면에서 로그인 후 **답변 문제 신고·수정**과 **내 수정안 검수**를 사용할 수 있습니다. 화면에서 승인한 자료를 JSONL로 내려받을 수 있습니다. [피드백 검수와 학습자료 안내](FEEDBACK.md)

## API 설명과 공통 오류

Swagger 첫 화면에는 전체 오류 코드 표가 표시됩니다. 각 API를 펼치면 한국어 기능 설명, 입력 조건, 응답 필드와 오류 코드별 예시를 확인할 수 있습니다. 내부 메서드는 함수 본문 첫 줄의 짧은 docstring으로 역할을 표시합니다.

모든 API는 `code`, `message`, `data`, `details` 형식을 사용합니다. 성공 결과는 `data`에 담습니다.

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
| `STUDY_SESSION_MAX_AGE_SECONDS` | `86400` | 로그인 세션과 쿠키의 최대 유지 시간(1일) |
| `STUDY_SESSION_IDLE_SECONDS` | `1800` | 인증 요청이 없는 세션의 만료 시간(30분). 최대 유지 시간 이내로 설정 |
| `STUDY_SESSION_COOKIE_SECURE` | `false` | 백엔드에 HTTP로 전달하는 HTTPS 프록시 환경에서 `true`로 설정. HTTPS 요청에는 자동 적용 |
| `STUDY_WEATHER_TIMEOUT_SECONDS` | `10` | 외부 날씨 API 제한 시간(0.1~30초) |
| `STUDY_WEATHER_CACHE_TTL_SECONDS` | `3600` | 예보를 최신으로 판단하는 시간(0~3600초, 0은 캐시 해제) |
| `STUDY_WEATHER_REDIS_URL` | 미설정 | Redis 예보 캐시 연결 주소. 미설정 또는 연결 장애 시 프로세스 메모리 캐시 사용 |
| `STUDY_WEATHER_CACHE_STALE_MAX_SECONDS` | `10800` | 메모리·Redis 예보의 최대 재사용 시간. 최신 유효 시간 이상, 최대 86400초 |
| `STUDY_LLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama 서버의 기본 주소 |
| `STUDY_LLM_MODEL` | 빈 문자열 | 직접 준비한 로컬 모델명 |
| `STUDY_LLM_THINKING` | 미지정 | Ollama 추론 모드. `true`/`false`, 미지정은 서버 기본값. 지원하는 모델에서만 설정 |
| `STUDY_LLM_TEMPERATURE` | `0.3` | 로컬 생성 온도(0~2). 값이 크다고 정확도가 높아지는 것은 아님 |
| `STUDY_LLM_TOP_P` | 미지정 | 로컬 누적 확률 후보 범위(0~1). 미지정은 모델 기본값 |
| `STUDY_LLM_MIN_P` | 미지정 | 로컬 최고 확률 대비 후보의 최소 비율(0~1). 미지정은 모델 기본값 |
| `STUDY_LLM_TIMEOUT_SECONDS` | `180` | 추론 응답 대기 시간(1~600초) |
| `STUDY_LLM_CONTEXT_SIZE` | `16384` | 요청 문맥 길이(2048~131072 정수). 모델·메모리에 맞춰 조절 |
| `STUDY_LLM_TODAY_CONTEXT_SIZE` | `4096` | 오늘 기본·개인 추천의 문맥 토큰 수. 주간은 일반 문맥 설정 유지 |
| `STUDY_LLM_CLOUD_FALLBACK_ENABLED` | `false` | `true`일 때 로컬 실패 후 Gemini 한 번 호출 |
| `STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS` | 20초 | 자동 전환을 켠 경우 로컬 요청당 적용. 지정값과 일반 로컬 대기 제한 중 작은 값 사용(1~600초) |
| `STUDY_OUTFIT_REFRESH_SECONDS` | `3600` | 조회한 지역의 추천 갱신 간격(60~86400초). 서버 실행 중 동작 |
| `STUDY_OUTFIT_WEATHER_REFRESH_WORKERS` | `4` | 시간별 시군구 예보 갱신의 최대 동시 요청 수(1~16) |
| `STUDY_OUTFIT_CACHE_MAX_ENTRIES` | `4096` | 공통 추천 보관 조합 수(1~100000). 지역·오늘/주간·모델 설정 조합 기준 |
| `STUDY_OUTFIT_WEEKLY_BATCH_HOUR` | `1` | 한국 시간 주간 배치 예약 시각(0~23). 기본 01:00부터 당일 배치 시작 |
| `STUDY_OUTFIT_WEEKLY_MAX_AGE_SECONDS` | `172800` | 주간 이전 정상 배치 결과의 최대 보관 시간(기본 48시간, 범위 1~7일) |
| `VWORLD_API_KEY` | 빈 문자열 | 브이월드 시군구 공식 경계 조회 키. 로컬 설정에만 저장 |
| `STUDY_VWORLD_DOMAIN` | 빈 문자열 | 브이월드 키 발급 시 등록한 이용 도메인. 예: `http://localhost:8000` |
| `GEMINI_API_KEY` | 빈 문자열 | Gemini API 키. 클라우드 전환 시 필요 |
| `STUDY_GEMINI_MODEL` | 빈 문자열 | JSON 스키마 출력을 지원하는 Gemini 모델명. 예: `gemini-flash-latest` |
| `STUDY_GEMINI_TIMEOUT_SECONDS` | `60` | Gemini 응답 대기 제한(1~300초) |
| `STUDY_GEMINI_MAX_OUTPUT_TOKENS` | `8192` | Gemini 출력 토큰 상한(128~32768 정수). 모델에 따라 내부 추론도 한도에 포함될 수 있음 |

설정 우선순위는 프로젝트 루트의 `.env` → 환경변수 → 코드 기본값입니다. `.env`에 작성한 값은 같은 이름의 환경변수보다 우선합니다. 파일 수정 후 서버를 재시작하면 반영됩니다. VS Code의 `python.terminal.useEnvFile`은 `false`로 두어도 코드가 직접 `.env`를 읽습니다. 상대 DB 경로는 프로젝트 루트 기준입니다. 서버 시작 시 테이블이 없으면 생성하고, 사용자 데이터는 DB 파일에 저장합니다. DB 파일과 `.env`는 Git에서 제외합니다.

DB 연결에는 Python 표준 라이브러리의 `sqlite3`를 사용합니다. `models.py`는 테이블 정의와 DB 행 매핑을 관리합니다. 기존 인증 테이블에 세션의 마지막 활동 시각 열이 없으면 서버 시작 시 추가합니다.

## 파일 역할

| 위치 | 역할 |
| --- | --- |
| `backend/main.py` | FastAPI 생성, 시작 시 테이블 초기화, 라우터 등록 |
| `run.cmd` / `run.ps1` | 가상환경 준비, 백엔드·프런트엔드 의존성 설치, 화면 빌드, 서버·테스트 실행 |
| `.vscode/tasks.json` / `.vscode/launch.json` | 환경 준비를 먼저 수행하는 실행·디버깅 설정 |
| `backend/app/common/config.py` | 환경변수와 `.env` 설정 읽기 |
| `backend/app/common/database.py` | DB 연결과 개발용 테이블 초기화 |
| `backend/app/common/responses.py` | 모든 API의 공통 응답 형식 |
| `backend/app/common/errors/` | 공통 오류 코드·응답 모델·예외 핸들러·Swagger 오류 문서 |
| `backend/app/outfits/` | 날씨 기반 LLM 추천·Gemini 자동 전환·오늘/주간 조회·응답 검증 |
| `backend/app/users/presentation/router.py` | 회원가입·로그인·로그아웃, 세션 쿠키와 계정·프로필 API |
| `backend/app/weather/presentation/router.py` | 국내 지역 검색, 오늘·주간 날씨 API |
| `backend/app/outfits/presentation/router.py` | 오늘·주간 옷차림 추천과 신고·수정안 검수 API |
| `backend/app/users/presentation/schemas.py` | Pydantic 요청·응답 형식 |
| `backend/app/users/application/services.py` | 사용자 등록·조회, 인증과 프로필 처리 |
| `backend/app/users/application/dto.py` | HTTP와 독립된 기능 입력·결과 데이터 |
| `backend/app/users/application/exceptions.py` | 사용자 조회와 인증 오류 |
| `backend/app/users/application/unit_of_work.py` | 트랜잭션과 저장소에 접근하기 위한 추상 계약 |
| `backend/app/users/domain/entities.py` | 사용자 객체, 이름·이메일 규칙 |
| `backend/app/users/domain/repositories.py` | 사용자 저장·조회 인터페이스 |
| `backend/app/users/domain/exceptions.py` | 잘못된 사용자 정보·이메일 중복 예외 |
| `backend/app/users/infrastructure/models.py` | 사용자 테이블 SQL과 DB 행 매핑 |
| `backend/app/users/infrastructure/repositories.py` | 파라미터 바인딩을 사용하는 실제 SQL 처리 |
| `backend/app/users/infrastructure/security.py` | scrypt 비밀번호 해시 생성과 비교 |
| `backend/app/users/infrastructure/unit_of_work.py` | 커밋, 롤백, 연결 종료 구현 |
| `backend/app/users/bootstrap.py` | 실제 DB 구현체를 Service에 주입 |
| `backend/tests/test_users.py` | 임시 SQLite DB를 사용하는 저장·중복·롤백 검증 |
| `backend/tests/test_startup.py` | 새 가상환경 생성, 재사용, 활성화 스크립트 복구, 설치 실패 시 중단 검증 |

## 요청 흐름과 의존성

DDD 실습용 사용자 등록 요청은 다음 순서로 처리합니다.

1. Router는 요청 스키마를 입력 DTO로 변환하고 Service를 호출합니다.
2. Service는 Domain 객체를 만들어 업무 규칙을 검증합니다.
3. Service는 Unit of Work를 열고 Repository 인터페이스로 조회·저장합니다.
4. SQLite Repository가 실제 SQL을 실행합니다.
5. Service가 커밋한 뒤 결과 DTO를 반환하고 Router가 응답 스키마로 변환합니다.

사용자 Domain은 업무 규칙을 정의합니다. Application은 Repository와 트랜잭션의 계약에 의존하고, SQLite 구현은 `bootstrap.py`에서 연결합니다. Unit of Work가 커밋과 롤백을 관리하고 연결을 닫습니다.

## API 예시

Swagger에서 DDD 실습용 `POST /api/v1/users`를 실행합니다.

```json
{
  "name": "김민성",
  "email": "minseong@example.com"
}
```

| 요청 | 정상 결과 | 주요 오류 |
| --- | --- | --- |
| `POST /api/v1/users` | `201`, 생성된 UUID·이름·이메일 | 이메일 중복 `409`, 잘못된 입력 `422` |
| `GET /api/v1/users/{user_id}` | `200`, 로그인한 본인의 사용자 정보 | 미인증·만료 `401`, 타인 조회 `403` |
| `GET /health` | `200`, `data.status`가 `ok` | 앱 응답 여부 확인용 |

이 요청은 이름 앞뒤의 공백을 제거하고 이메일을 소문자로 정규화한 뒤 사용자 레코드를 생성합니다. 로그인 가능한 계정은 비밀번호와 함께 `POST /api/v1/users/auth/register`로 등록합니다.

## 검증

```powershell
.\run.cmd -Test
```

테스트마다 임시 DB를 만들고 종료 시 정리하므로 실제 `study.db`에 테스트 데이터를 남기지 않습니다.

## 다음 업무 추가

새 업무는 `backend/app/` 아래 4개 계층과 `bootstrap.py`를 배치하고 `backend/main.py`에서 라우터를 등록합니다. 옷차림 추천의 외부 날씨 연결처럼 다른 업무의 구현을 사용하는 부분은 infrastructure에 둡니다. 공통 폴더에는 여러 업무가 사용하는 환경 설정·DB 연결·응답 형식을 둡니다.
