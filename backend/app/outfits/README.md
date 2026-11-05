# LLM 옷차림 추천

오늘·7일 예보를 로컬 Ollama에 보내 베스트·워스트 옷차림과 구성 이유를 생성합니다. 설정을 켜면 로컬 실패 시 OpenAI API로 자동 전환합니다. 고정 `BANDS` 의류 목록은 제거했으며 모델 설치·다운로드는 자동 실행하지 않습니다. 이미지, 인기 순위, 개인 취향과 보유 의류는 후속 작업입니다.

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
| `infrastructure/openai_client.py` | OpenAI Responses API와 통신 오류 처리 |
| `infrastructure/structured_recommender.py` | 두 제공사의 공통 JSON 검증과 도메인 변환 |
| `infrastructure/ollama_recommender.py`, `openai_recommender.py` | 제공사와 오류 코드 지정 |
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

## OpenAI 자동 전환

ChatGPT 화면을 조작하는 방식이 아닌 OpenAI API 연동입니다. API 사용 요금은 ChatGPT 구독과 별도입니다. `.env`에 아래 설정을 추가하고 서버를 재시작합니다. 기본값은 `false`이며 API 키와 모델을 자동 선택하지 않습니다.

```dotenv
STUDY_LLM_CLOUD_FALLBACK_ENABLED=true
STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS=15
OPENAI_API_KEY=발급받은_API_키
STUDY_OPENAI_MODEL=사용할_API_모델명
STUDY_OPENAI_TIMEOUT_SECONDS=60
STUDY_OPENAI_MAX_OUTPUT_TOKENS=8192
```

Responses API와 Structured Outputs를 지원하는 모델을 선택하세요. 로컬 미설정·모델 없음·연결 실패·시간 초과·잘못된 생성 결과에만 OpenAI를 한 번 호출합니다. 로컬 성공 시 클라우드 클라이언트를 생성하지 않습니다. 전환을 켜면 로컬 응답 대기 제한은 기존 제한과 전환용 제한 중 작은 값입니다. 로컬 모델이 느리면 15초 설정을 늘려야 불필요한 클라우드 전환을 줄일 수 있습니다.

날씨 조회·입력 오류는 전환 대상이 아닙니다. OpenAI까지 실패하면 공통 클라우드 오류를 반환하며 반복 재시도하지 않습니다. 로컬 모델을 비워두고 자동 전환을 켜면 바로 OpenAI로 연결할 수도 있습니다.

OpenAI에는 날짜별 날씨·단위·스키마·추천 지침만 전달합니다. 정확한 좌표·사용자 계정은 보내지 않습니다. 요청은 고정 HTTPS 주소 `/v1/responses`, `stream: false`, `store: false`, `text.format`의 엄격한 JSON 스키마를 사용합니다. `store: false`는 Responses 상태 저장을 끄는 옵션이며 모든 보존 정책을 해제한다는 뜻은 아닙니다. 출력·추론 토큰을 합친 상한을 설정할 수 있고, 요청 횟수나 전체 비용 상한은 별도 관리해야 합니다.

### 다른 컴퓨터에서 자동 전환 설정

자동 전환 기능이 포함된 코드를 받은 뒤, 각 컴퓨터의 프로젝트 루트에 있는 `.env`를 수정합니다. `.env.example`은 설정 예시이며 서버에서 직접 읽지 않습니다. 기존 `.env`의 로컬 모델명과 주소는 유지하고 다음 항목을 설정합니다. API 키는 발급받은 실제 값으로 입력하며 Git에 올리지 않습니다.

```dotenv
STUDY_LLM_CLOUD_FALLBACK_ENABLED=true
STUDY_LLM_FALLBACK_LOCAL_TIMEOUT_SECONDS=180
OPENAI_API_KEY=발급받은_API_키
STUDY_OPENAI_MODEL=사용할_API_모델명
```

위 예시는 느린 로컬 모델을 기다리도록 대기 시간을 180초로 설정합니다. 실제 로컬 대기 제한은 `STUDY_LLM_TIMEOUT_SECONDS`와 이 값 중 작은 값입니다. 연결이 즉시 거부되면 이 시간을 모두 기다리지 않고 클라우드로 전환하지만, 서버가 응답 없이 대기하면 제한 시간이 지난 뒤 전환합니다. 필요에 따라 로컬 생성 시간에 맞춰 조정합니다.

설정을 저장한 뒤 FastAPI를 재시작합니다. Ollama가 정상일 때 추천 응답의 `data.engine.provider`는 `ollama`, `fallback_used`는 `false`입니다. 자동 전환을 확인하려면 Ollama 트레이 앱을 완전히 종료하고 같은 옷차림 API를 호출합니다. 성공 시 `provider`는 `openai`, `fallback_used`는 `true`, `fallback_reason`은 `OUTFIT_LLM_UNAVAILABLE`로 표시됩니다. 이 확인 과정에서는 실제 OpenAI API 사용 요금이 발생합니다. 사용 후 Ollama 앱을 다시 실행하면 다음 요청은 다시 로컬부터 시도합니다.

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
- 로컬 실패 시 자동 전환을 켰으면 OpenAI로 재요청합니다. 최종 실패 시 고정 의류·샘플 응답 없이 정해진 오류를 반환합니다.
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
| `OUTFIT_CLOUD_NOT_CONFIGURED` | 503 | OpenAI API 키 또는 모델 미설정 |
| `OUTFIT_CLOUD_AUTH_ERROR` | 503 | API 키·접근 권한 오류(401·403) |
| `OUTFIT_CLOUD_RATE_LIMITED` | 503 | API 요청 한도·크레딧 부족(429) |
| `OUTFIT_CLOUD_UNAVAILABLE` | 503 | 연결 실패·지원하지 않는 모델/요청 설정·API 서버 오류 |
| `OUTFIT_CLOUD_TIMEOUT` | 504 | API 응답 시간 초과 |
| `OUTFIT_CLOUD_INVALID_RESPONSE` | 502 | 거절·생성 중단·잘못된 JSON·날짜·구성 |

날씨 조회 오류는 기존 WEATHER_* 코드로 전파합니다. 프로젝트 루트에서 `run.cmd -Test`로 검증합니다. `test_outfits.py`, `test_ollama.py`, `test_openai.py`, `test_fallback.py`는 모의 LLM·합성 예보로 요청 구성·JSON 검증·오류·날짜·캐시 공유와 자동 전환을 확인합니다. 실제 Ollama·OpenAI API의 연결과 생성 품질은 별도로 검증합니다. 자동 테스트는 유료 API를 호출하지 않습니다.

공식 문서: [채팅 API](https://docs.ollama.com/api/chat), [구조화 출력](https://docs.ollama.com/capabilities/structured-outputs), [문맥 길이](https://docs.ollama.com/context-length).

OpenAI: [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [ChatGPT와 API 과금 구분](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform).
