# LLM 옷차림 추천

오늘·7일 예보를 로컬 Ollama에 보내 베스트·워스트 옷차림과 구성 이유를 생성합니다. 설정을 켜면 로컬 실패 시 Gemini API로 자동 전환합니다. 고정 `BANDS` 의류 목록은 제거했으며 모델 설치·다운로드는 자동 실행하지 않습니다. 이미지, 인기 순위, 개인 취향과 보유 의류는 후속 작업입니다.

## 계층과 흐름

날씨 조회 → 원본 예보 검증 → LLM 요청 → 생성 JSON 검증 → 원본 날씨 결합 → 공통 응답 순서입니다. 오늘은 하루, 주간은 7일을 한 번의 추론 요청으로 전달합니다.

| 파일 | 역할 |
| --- | --- |
| `presentation/router.py`, `schemas.py` | API 입력·출력과 Swagger 설명 |
| `application/services.py` | 조회·생성 절차, 날짜·원본 날씨 일치 확인 |
| `application/ports.py` | OutfitWeatherReader와 OutfitRecommender 계약 |
| `application/fallback.py` | 로컬 우선·허용된 오류에만 클라우드 한 번 호출 |
| `application/dto.py` | 예보·생성 결과·추론 제공사 정보 |
| `domain/models.py`, `rules.py` | 날씨·의류 모델, 온도 기준과 주간 의류 집계 |
| `infrastructure/weather_reader.py` | 기존 WeatherService와 캐시 재사용 |
| `infrastructure/ollama_client.py` | Ollama HTTP 요청과 통신 오류 처리 |
| `infrastructure/gemini_client.py` | Google GenAI SDK 호출, 응답 검증과 클라우드 오류 변환 |
| `infrastructure/structured_recommender.py` | 두 제공사의 공통 JSON 검증과 도메인 변환 |
| `infrastructure/ollama_recommender.py`, `gemini_recommender.py` | 제공사와 오류 코드 지정 |
| `infrastructure/llm_schemas.py` | 모델이 반환해야 하는 JSON 스키마 |
| `infrastructure/prompts.py` | 한국어 추천 프롬프트와 날씨 입력 구성 |
| `bootstrap.py` | 설정에 따라 로컬 전용 또는 자동 전환 구현 주입 |

Domain·Application은 weather 모듈·FastAPI·Pydantic·외부 LLM 클라이언트를 import하지 않습니다. 추론 서버를 바꾸려면 OutfitRecommender를 구현하고 bootstrap의 연결을 교체합니다. 현재 구현을 LM Studio/vLLM에 그대로 연결하는 호환 기능은 아직 없습니다.

## 로컬 연결 준비

1. [Ollama Windows 안내](https://docs.ollama.com/windows)에 따라 서버를 별도로 준비합니다.
2. 사용할 모델을 직접 선택·준비하고 `ollama list`에서 정확한 모델명을 확인합니다. JSON 스키마 출력과 한국어 생성이 가능한 모델로 실제 결과를 확인해야 합니다.
3. 프로젝트 루트의 `.env.example`을 `.env`로 복사하고 다음 값을 설정합니다. `STUDY_LLM_MODEL`에는 설치한 모델명을 입력합니다.

```dotenv
STUDY_LLM_BASE_URL=http://127.0.0.1:11434
STUDY_LLM_MODEL=
STUDY_LLM_TIMEOUT_SECONDS=180
STUDY_LLM_CONTEXT_SIZE=16384
```

기본 주소는 FastAPI가 실행되는 컴퓨터의 Ollama입니다. 모델명은 자동 선택하지 않습니다. 모델 미설정 상태에서도 서버와 날씨 API는 사용할 수 있으며 옷차림 API는 안내용 503을 반환합니다. 설정 변경 후 FastAPI를 재시작합니다.

현재 요청은 `/api/chat`, `stream: false`, JSON 스키마 `format`을 사용합니다. 생성 온도는 0.3, 출력 토큰 상한은 8192이며 요청 문맥 길이는 환경변수로 조절합니다. 문맥을 늘리면 메모리 사용도 증가합니다. 주간 JSON이 잘리거나 느리면 모델·문맥 길이·대기 시간을 함께 조정해야 합니다. 코드에서 모델을 내려받거나 Ollama를 실행하지는 않습니다.

## Gemini 자동 전환

클라우드 추천은 Google Gemini API를 호출합니다. `.env`에 아래 값을 입력하고 FastAPI를 재시작합니다. 자동 전환 기본값은 `false`이며 API 키와 모델명을 코드에서 자동 발급하거나 선택하지 않습니다. 기존 `OPENAI_API_KEY`, `STUDY_OPENAI_*` 설정은 더 이상 사용하지 않습니다.

```dotenv
STUDY_LLM_CLOUD_FALLBACK_ENABLED=true
GEMINI_API_KEY=발급받은_API_키
STUDY_GEMINI_MODEL=gemini-flash-latest
STUDY_GEMINI_TIMEOUT_SECONDS=60
STUDY_GEMINI_MAX_OUTPUT_TOKENS=8192
```

JSON 스키마 출력을 지원하는 Gemini 모델을 설정하세요. 로컬 모델 미설정·모델 없음·연결 실패·시간 초과·잘못된 응답이면 Gemini를 한 번 호출합니다. 로컬 성공 시 클라우드 클라이언트를 생성하지 않습니다. 자동 전환을 켜도 일반 로컬 대기 제한 `STUDY_LLM_TIMEOUT_SECONDS`(기본 180초)를 유지합니다. `STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS`를 명시한 경우에만 두 제한 중 작은 값을 적용합니다. 이 설정을 생략하거나 비워두면 모델 로딩과 생성에 기존 대기 시간을 그대로 사용할 수 있습니다.

날씨 조회·입력 오류는 전환 대상이 아닙니다. Gemini까지 실패하면 공통 클라우드 오류를 반환하며 반복 재시도하지 않습니다. 로컬 모델을 비워두고 자동 전환을 켜면 바로 Gemini로 연결할 수도 있습니다.

Gemini는 `google-genai` 공식 SDK의 `client.models.generate_content()`로 호출합니다. 날짜별 날씨·단위·출력 스키마·추천 지침을 전달하며 정확한 좌표와 사용자 식별 정보는 보내지 않습니다. `GenerateContentConfig`에 시스템 지시문, JSON MIME 형식과 원본 JSON 스키마를 지정하고 완료된 단일 후보의 최종 텍스트를 검증합니다. SDK 클라이언트는 요청 종료 시 닫습니다. 기존 `.env` 설정 이름과 API 응답 형식은 그대로 사용합니다.

### 공식 SDK 설정

`run.cmd`는 `backend/requirements.txt`의 `google-genai==2.34.0`을 설치합니다. 직접 설치할 때는 프로젝트 루트에서 `.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt`를 실행합니다.

설정의 대기 시간은 초 단위이며 SDK의 `HttpOptions.timeout`에 전달할 때 밀리초로 변환합니다. SDK 자동 재시도는 총 시도 횟수 1회로 제한하고 자동 후속 생성과 자동 함수 호출도 비활성화합니다. 여러 요청이 암묵적으로 이어져 대기 시간이나 사용량이 늘어나는 것을 방지하기 위한 설정입니다. 이 제한은 전체 날씨 조회·로컬·클라우드 처리를 합친 10초 응답 보장을 의미하지 않습니다.

SDK의 인증·할당량·서비스 장애와 시간 초과는 기존 공통 오류 코드로 변환합니다. 오류 원인은 키를 가린 서버 로그에 기록하며, 정상 완료되지 않은 결과와 출력 상한을 넘는 텍스트는 거부합니다. SDK 사용만으로 Google 서버의 503이나 네트워크 지연이 해결되는 것은 아닙니다.

### 다른 컴퓨터에서 자동 전환 설정

자동 전환 기능이 포함된 코드를 받은 뒤, 각 컴퓨터의 프로젝트 루트에 있는 `.env`를 수정합니다. 기존 `.env`의 로컬 모델명과 주소는 유지하고 다음 항목을 설정합니다. API 키는 발급받은 실제 값으로 입력하며 Git에 올리지 않습니다.

```dotenv
STUDY_LLM_CLOUD_FALLBACK_ENABLED=true
STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS=180
GEMINI_API_KEY=발급받은_API_키
STUDY_GEMINI_MODEL=gemini-flash-latest
```

위 예시는 느린 로컬 모델을 기다리도록 대기 시간을 180초로 설정합니다. 실제 로컬 대기 제한은 `STUDY_LLM_TIMEOUT_SECONDS`와 이 값 중 작은 값입니다. 연결이 즉시 거부되면 이 시간을 모두 기다리지 않고 클라우드로 전환하지만, 서버가 응답 없이 대기하면 제한 시간이 지난 뒤 전환합니다. 필요에 따라 로컬 생성 시간에 맞춰 조정합니다.

설정을 저장한 뒤 FastAPI를 재시작합니다. Ollama가 정상일 때 추천 응답의 `data.engine.provider`는 `ollama`, `fallback_used`는 `false`입니다. 자동 전환을 확인하려면 Ollama 트레이 앱을 완전히 종료하고 같은 옷차림 API를 호출합니다. 성공 시 `provider`는 `gemini`, `fallback_used`는 `true`, `fallback_reason`은 `OUTFIT_LLM_UNAVAILABLE`로 표시됩니다. 이 확인 과정에서는 Gemini API 할당량을 사용하며 계정의 요금제에 따라 비용이 발생할 수 있습니다. 사용 후 Ollama 앱을 다시 실행하면 다음 요청은 다시 로컬부터 시도합니다.

## 추천 저장과 시간별 갱신

오늘·주간 API는 날씨와 추천 결과 전체를 기존 SQLite DB의 `outfit_result_cache` 테이블에 보관합니다. 같은 지역·조회 종류·모델 설정의 결과가 있으면 날씨와 LLM을 다시 호출하지 않고 반환합니다. 저장값은 서버를 재시작해도 유지하며, 모델·프롬프트 설정이 달라지면 별도로 생성합니다. API 응답 형식은 유지하고 `fetched_at`으로 사용한 날씨의 조회 시각을 확인할 수 있습니다.

기존 캐시 테이블에 `requested_at` 컬럼이 없는 경우 서버 시작 시 같은 트랜잭션에서 컬럼을 추가하고 마지막 저장·시도 시각으로 초기화합니다. 저장된 추천과 사용자 데이터는 유지하며 재실행 시 중복 변경하지 않습니다. DB 파일을 삭제하거나 테이블을 재생성할 필요가 없습니다.

- 처음 조회한 지역과 종류는 한 번 생성한 뒤 이후 조회부터 저장값을 사용합니다. 아직 조회하지 않은 지역은 미리 생성하지 않습니다.
- 서버가 실행 중일 때 최근 24시간 내 조회한 지역을 기본 1시간 간격으로 갱신합니다. 서버 시작 시에도 갱신 기한이 지난 저장 지역을 확인합니다. 서버나 PC가 꺼져 있으면 작업하지 않습니다.
- `.env`의 `STUDY_OUTFIT_REFRESH_SECONDS`로 주기를 조정합니다(기본 3600초, 범위 60~86400초). 설정 변경 후 서버를 재시작합니다. 기한 확인은 1분 간격이며 생성은 순차 실행하므로 여러 지역의 완료 시각은 달라질 수 있습니다.
- 생성 중에는 기존 정상 결과를 제공합니다. 갱신 실패는 결과를 덮어쓰지 않고 다음 갱신 주기에 재시도합니다. 마지막 저장 후 주기의 3배(기본 3시간)를 넘거나 한국 날짜가 바뀐 결과는 사용하지 않고 다음 조회에서 새로 생성합니다.
- 같은 지역의 동시 최초 요청은 프로세스 안에서 한 번만 생성합니다. 보관량은 최근 조회한 최대 128개 지역·종류·모델 조합이며, 24시간 동안 조회하지 않은 조합은 자동 갱신을 중단합니다.
- 자동 갱신도 기존 로컬 우선·Gemini 전환 설정을 사용합니다. 전환이 켜져 있으면 백그라운드 작업에서도 Gemini 할당량을 사용할 수 있습니다. 로컬이 복구되면 다음 갱신부터 다시 로컬을 시도합니다.

현재 실행 스크립트처럼 API 작업 프로세스 하나로 실행하는 구성을 기준으로 합니다. 여러 프로세스로 운영하면 작업 프로세스마다 갱신할 수 있으므로 별도 작업자 분리가 필요합니다. 외부 예약 작업이나 Codex 알림은 생성하지 않습니다.

## API와 응답

`run.cmd` 실행 후 `/docs`의 outfits 항목에서 호출합니다. 지역은 기존 `/api/v1/weather/locations`에서 검색합니다.

| API | 역할 |
| --- | --- |
| `GET /api/v1/outfits/today?latitude=37.5665&longitude=126.978` | 오늘의 추천·비추천 옷차림과 이유 |
| `GET /api/v1/outfits/weekly?latitude=37.5665&longitude=126.978` | 오늘부터 7일 추천과 공통 준비 의류 |

공통 `code`, `message`, `data`, `details` 형식과 API 경로는 유지합니다. 기존 `data.rule_version`은 제거하고 `data.engine`으로 변경했습니다.

| data 필드 | 의미 |
| --- | --- |
| `coordinates`, `timezone`, `fetched_at` | 요청 위치·한국 시간대·원본 날씨 조회 시각 |
| `provider`, `source_url` | 날씨 제공사와 출처 |
| `engine.provider`, `engine.model`, `engine.prompt_version` | 옷차림 생성 제공사·모델명·프롬프트 버전 |
| `engine.fallback_used`, `engine.fallback_reason` | 클라우드 자동 전환 여부와 원인이 된 로컬 오류 코드. 전환하지 않으면 false·null |
| `recommendation` | 오늘의 날씨·온도 기준·best·worst·추천 이유·비추천 이유·참고 사항 |
| `daily` | 주간 응답의 날짜별 추천 7개 |
| `wardrobe` | 주간 베스트 의류 종류. 동일 문자열을 중복 제거하며 수량은 산정하지 않음 |
| `summary` | 서버가 원본 예보로 구성한 주간 최저·최고기온 안내 |

## 생성과 검증 기준

- 최저·최고 체감온도가 모두 있으면 체감온도를 사용합니다. 하나라도 없으면 실제 기온을 기준으로 지정하고 이유를 덧붙입니다. 원본의 null 값은 유지합니다.
- LLM에는 기온·체감온도·비·눈·바람·자외선·날씨 한글 설명과 출력 스키마를 보냅니다. 모델은 의류와 설명만 생성합니다.
- 날짜·개수·순서·필수 필드·문자열 길이와 타입을 검증하고 동일한 베스트·워스트는 거부합니다. 모델이 날씨나 추가 필드를 반환해 원본을 덮어쓸 수 없습니다.
- JSON 검증은 형식과 원본 데이터 보존을 확인합니다. 자유 문장에 담긴 판단의 정확성과 모델별 추천 품질까지 보장하는 것은 아닙니다.
- 로컬 실패 시 자동 전환을 켰으면 Gemini로 재요청합니다. 최종 실패 시 고정 의류·샘플 응답 없이 정해진 오류를 반환합니다.
- 날씨 캐시는 재사용하지만 생성 결과는 캐시하지 않습니다. 같은 날씨여도 모델·실행 시점에 따라 추천 문장이 달라질 수 있습니다.

## 오류와 테스트

| 코드 | HTTP | 원인 |
| --- | --- | --- |
| `OUTFIT_LLM_NOT_CONFIGURED` | 503 | 모델명 미설정 |
| `OUTFIT_LLM_MODEL_NOT_FOUND` | 503 | Ollama가 모델을 찾지 못함(404) |
| `OUTFIT_LLM_UNAVAILABLE` | 503 | 서버 연결 실패·추론 오류 |
| `OUTFIT_LLM_TIMEOUT` | 504 | 추론 응답 시간 초과 |
| `OUTFIT_LLM_INVALID_RESPONSE` | 502 | 잘못된 JSON·날짜·구성 또는 출력 잘림 |
| `OUTFIT_INVALID_FORECAST` | 502 | 잘못된 추천용 날씨·7일 날짜 |
| `OUTFIT_CLOUD_NOT_CONFIGURED` | 503 | Gemini API 키 또는 모델 미설정 |
| `OUTFIT_CLOUD_AUTH_ERROR` | 503 | API 키·접근 권한 오류(401·403) |
| `OUTFIT_CLOUD_RATE_LIMITED` | 503 | API 요청 한도·크레딧 부족(429) |
| `OUTFIT_CLOUD_UNAVAILABLE` | 503 | 연결 실패·지원하지 않는 모델/요청 설정·API 서버 오류 |
| `OUTFIT_CLOUD_TIMEOUT` | 504 | API 응답 시간 초과 |
| `OUTFIT_CLOUD_INVALID_RESPONSE` | 502 | 거절·생성 중단·잘못된 JSON·날짜·구성 |

날씨 조회 오류는 기존 WEATHER_* 코드로 전파합니다. 프로젝트 루트에서 `run.cmd -Test`로 검증합니다. `test_outfits.py`, `test_ollama.py`, `test_gemini.py`, `test_fallback.py`는 모의 LLM·합성 예보로 요청 구성·JSON 검증·오류·날짜·캐시 공유와 자동 전환을 확인합니다. 실제 Ollama·Gemini API의 연결과 생성 품질은 별도로 검증합니다. 자동 테스트는 유료 API를 호출하지 않습니다.

공식 문서: [채팅 API](https://docs.ollama.com/api/chat), [구조화 출력](https://docs.ollama.com/capabilities/structured-outputs), [문맥 길이](https://docs.ollama.com/context-length).

Gemini: [콘텐츠 생성 API](https://ai.google.dev/api/generate-content), [구조화된 출력](https://ai.google.dev/gemini-api/docs/structured-output), [API 키 설정](https://ai.google.dev/gemini-api/docs/api-key).

Google GenAI: [Python 공식 SDK](https://googleapis.github.io/python-genai/).
