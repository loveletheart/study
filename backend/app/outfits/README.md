# LLM 옷차림 추천

오늘·7일 예보를 로컬 Ollama에 보내 베스트·워스트 옷차림과 구성 이유를 생성합니다. 설정을 켜면 로컬 실패 시 Gemini API로 자동 전환합니다. 고정 `BANDS` 의류 목록은 제거했으며 모델 설치·다운로드는 자동 실행하지 않습니다. 이미지, 인기 순위, 개인 취향과 보유 의류는 후속 작업입니다.

## 계층과 흐름

날씨 조회 → 원본 예보 검증 → LLM 요청 → 생성 JSON 검증 → 원본 날씨 결합 → 공통 응답 순서입니다. 오늘은 하루, 주간은 7일을 한 번의 추론 요청으로 전달합니다.

| 파일 | 역할 |
| --- | --- |
| `presentation/router.py`, `schemas.py` | API 입력·출력과 Swagger 설명 |
| `application/services/outfit_service.py` | 조회·생성 절차, 날짜·원본 날씨 일치 확인 |
| `application/services/neighborhood_service.py` | 공식 시군구 공통 추천과 동적 개인화 조합 |
| `application/ports.py` | OutfitWeatherReader와 OutfitRecommender 계약 |
| `application/policies/fallback_recommender.py` | 로컬 우선·허용된 오류에만 클라우드 한 번 호출하는 실행 정책 |
| `domain/preferences.py` | 사용자 선택 조건. 사용자에게 보여줄 문장이나 템플릿을 포함하지 않음 |
| `infrastructure/llm_personalizer.py` | 기본 추천·날씨·선택 조건을 전달해 실제 개인화 의류·설명 생성 |
| `infrastructure/personalized_cache.py` | 개인 조건 조합의 영속 캐시와 10분 전 사전 생성 |
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
- 서버가 실행 중일 때 최근 24시간 내 조회한 지역의 날씨를 기본 1시간 간격으로 확인합니다. 오늘 추천은 오늘의 입력값, 주간 추천은 7일의 입력값을 비교해 같은 경우에는 기존 추천·생성 버전을 재사용합니다. 날씨 조회 시각만 달라져도 LLM을 재호출하지 않습니다. 서버 시작 시에도 갱신 기한이 지난 저장 지역을 확인합니다. 서버나 PC가 꺼져 있으면 작업하지 않습니다.
- `.env`의 `STUDY_OUTFIT_REFRESH_SECONDS`로 주기를 조정합니다(기본 3600초, 범위 60~86400초). 설정 변경 후 서버를 재시작합니다. 기한 확인은 1분 간격이며 백그라운드 갱신은 순차 실행하므로 여러 지역의 완료 시각은 달라질 수 있습니다. 생성 잠금은 캐시 키별로 공유하여 다른 지역·조회 종류의 최초 요청은 진행 중인 갱신을 기다리지 않습니다.
- 생성 중에는 기존 정상 결과를 제공합니다. 갱신 실패는 결과를 덮어쓰지 않고 다음 갱신 주기에 재시도합니다. 마지막 저장 후 주기의 3배(기본 3시간)를 넘거나 한국 날짜가 바뀐 결과는 사용하지 않고 다음 조회에서 새로 생성합니다.
- 같은 지역의 동시 최초 요청은 프로세스 안에서 한 번만 생성합니다. 보관량은 `STUDY_OUTFIT_CACHE_MAX_ENTRIES`로 지정합니다(기본 4096개, 범위 1~100000). 지역·종류·모델 조합 기준이며, 24시간 동안 조회하지 않은 조합은 자동 갱신을 중단합니다.
- 자동 갱신도 기존 로컬 우선·Gemini 전환 설정을 사용합니다. 전환이 켜져 있으면 백그라운드 작업에서도 Gemini 할당량을 사용할 수 있습니다. 로컬이 복구되면 다음 갱신부터 다시 로컬을 시도합니다.

현재 실행 스크립트처럼 API 작업 프로세스 하나로 실행하는 구성을 기준으로 합니다. 여러 프로세스로 운영하면 작업 프로세스마다 갱신할 수 있으므로 별도 작업자 분리가 필요합니다. 외부 예약 작업이나 Codex 알림은 생성하지 않습니다.

## 동네 공통 추천과 개인화

1. `GET /api/v1/weather/locations?query=원하는지역`으로 검색합니다. 검증된 국내 검색 결과는 SQLite의 `weather_locations`에 저장되어 서버 재시작 후에도 대표 좌표를 확인할 수 있습니다.
2. 반환된 `id`를 아래 `location_id`에 넣습니다. 클라이언트가 임의 대표 좌표를 보내거나 개인 좌표를 소수점 반올림해 구역으로 취급하지 않습니다. 알 수 없는 식별자는 `WEATHER_INVALID_QUERY`(422)로 안내합니다.
3. 검색 좌표를 브이월드 `LT_C_ADSIGG_INFO`의 `POINT(경도 위도)` 조건과 `EPSG:4326`으로 조회합니다. 결과의 `sig_cd`가 같은 위치는 공통 추천과 같은 조건의 개인화를 공유합니다. 검색 ID나 이름이 달라도 같은 시군구면 하나로 묶입니다. 결과가 없거나 둘 이상이면 구역을 임의 선택하지 않고 요청 오류로 안내합니다.
4. 시군구 대표 좌표는 그 경계 안에 있다고 처음 검증한 검색 좌표로 고정해 저장합니다. 구청 좌표나 행정경계의 중심점을 임의로 만들어 쓰지 않습니다. 이후 같은 코드의 다른 좌표는 이 대표점을 재사용합니다. 넓은 시군구 안의 산간·해안 등 세부 날씨 차이는 이 공통 추천에 반영되지 않을 수 있습니다. 좌표의 시군구 판정은 24시간 보관 후 다시 확인합니다.

```text
GET /api/v1/outfits/regions/{location_id}/today?cold_sensitivity=cold&style=formal&activity=outdoor
GET /api/v1/outfits/regions/{location_id}/weekly?activity=active
```

| 옵션 | 허용값 | 의미 |
| --- | --- | --- |
| `cold_sensitivity` | `normal`, `cold`, `warm` | 보통, 추위를 많이 탐, 더위를 많이 탐 |
| `style` | `default`, `casual`, `formal` | 기본, 편안한 디자인, 단정한 디자인 |
| `activity` | `daily`, `outdoor`, `active` | 일상, 야외, 활동량 많음 |

응답의 `location`은 선택한 검색 지역과 대표 좌표입니다. `generated_at`과 `base_version`은 동네 공통 추천이 실제 생성된 시각과 버전이며, 날씨 입력이 그대로인 갱신에서는 유지됩니다. `fetched_at`은 가장 최근 정상 확인한 날씨의 조회 시각입니다. 구버전 저장값에는 생성 메타데이터가 없을 수 있어 null을 허용합니다.

`region`에는 공통 추천을 나누는 실제 시군구 코드·이름·고정 대표점·출처가 표시됩니다. `location.id`는 여전히 사용자가 검색에서 선택한 GeoNames 식별자이며 `region.code`와 다릅니다. 검색 좌표가 곧 공통 추천 좌표라고 가정하지 말고 응답의 `coordinates`와 `region`을 확인하세요.

`personalization`에는 적용한 개인 옵션, 동적 생성 설명, `llm_used`, `cache_hit`, `generated_at`, `version`, 개인화 `engine`이 표시됩니다. `llm_used`는 결과 생성에 모델을 사용했는지 뜻하며 이번 요청에서 추가 호출했는지는 `cache_hit`과 함께 확인합니다. 바깥쪽 `engine`·`generated_at`·`base_version`은 공통 기본 추천의 정보입니다. 개인화 결과는 별도 생성 버전과 제공사 정보를 갖고 기본 추천을 덮어쓰지 않습니다.

모든 옵션이 기본값이면 공통 추천을 그대로 사용합니다. 나머지는 기본 추천·원본 날씨·명시한 옵션으로 LLM이 의류 구성·이유·주의사항을 실제로 생성합니다. 정해진 수식어를 옷 이름에 붙이거나 고정 설명을 합성하지 않습니다. 기존 JSON 스키마·날짜·날씨 보존·베스트/워스트 구분을 검증하며, 무더위와 방한에 관한 제약도 프롬프트에 전달합니다. 자유 문장 생성의 판단 품질을 규칙처럼 보장하는 것은 아니므로 모델별 실제 품질은 따로 확인해야 합니다. 개인화한 주간 준비물은 생성된 의류에 맞춰 다시 구성합니다.

캐시 키는 시군구·조회 종류·공통 생성 버전·개인 조건·개인화 모델/프롬프트 설정입니다. 사용자 ID를 포함하지 않으므로 같은 지역과 조건을 공유하며, 개인 조건마다 최초 한 번은 생성 시간이 필요합니다. 개인화 프롬프트 버전은 공통 추천 프롬프트와 별개입니다. 기존 규칙으로 생성한 결과는 이 캐시에 들어 있지 않습니다.

### 공통 갱신 10분 전 준비

- 최근 24시간에 요청한 개인 조건만 대상으로 하고 1분 간격으로 기한을 확인합니다.
- 공통 추천의 다음 갱신 예정이 11:00이면 10:50부터 새 날씨를 먼저 확인합니다. 필요한 공통 생성이 끝난 새 버전에 맞춰 개인화를 생성합니다. 오래된 기본 추천만 개인화해 바로 무효가 되는 일을 방지하기 위한 순서입니다. 준비된 공통 결과는 완료 시점부터 조회에 사용할 수 있습니다.
- 사전 확인한 날씨가 같으면 기존 기본 버전과 개인 캐시를 재사용합니다. 정규 11:00 갱신에서는 준비된 결과를 인정하고 다음 공통 기한을 12:00으로 유지해 갱신 일정이 10분씩 앞당겨지지 않게 합니다.
- 개인화 대상은 순차 처리하고 동일 조합은 키별 잠금으로 중복 생성하지 않습니다. 사전 생성 실패는 같은 주기에 무한 반복하지 않으며 잘못된 결과는 저장하지 않습니다. 요청에서의 명시적 재시도와 다음 갱신 주기는 별개입니다.
- 10분은 준비 시작 목표이며 모델 처리량·지역과 조건 조합 수에 따라 완료를 보장하지 않습니다. 처음 등장한 조건이나 준비되지 않은 조합은 요청 시 생성합니다.
- 다음 기한이 한국 날짜 변경을 가로지르면 전날 예보로 다음 날 추천을 미리 확정하지 않습니다. 날짜 변경 후 정상 예보로 새로 생성하며 이 경우 최초 개인 요청은 느릴 수 있습니다.
- 서버가 실행 중이어야 하며 백그라운드 작업은 요청 시각을 갱신하지 않으므로 사용이 끊긴 조건이 무기한 생성되지 않습니다. 개인화도 기존 로컬 우선·명시적 클라우드 전환 설정을 사용하므로 설정에 따라 비용이 발생할 수 있습니다.

현재 개인 옵션은 요청별로 전달하고, 사전 생성을 위해 사용자 ID 없이 조건 조합만 별도 테이블에 저장합니다. 계정별 기본 설정으로 저장하지 않으므로 클라이언트는 선택한 옵션을 다음 요청에 다시 전달해야 합니다. 임의의 자유 문장 취향 입력은 아직 지원하지 않습니다.

날씨 재생성 기준은 보수적으로 모델에 전달하는 모든 일별 입력값의 정확한 일치 여부를 사용합니다. 작은 기온 변화나 null과 0의 전환도 재생성 대상이며, 임의 임계값으로 무시해 이전 자유 문장의 기온·강수 설명과 최신 날씨가 어긋나는 문제를 방지합니다. 날짜 변경이나 캐시 만료도 새 생성 대상입니다.

시군구 판정에는 로컬 `.env`의 `VWORLD_API_KEY`와 등록 도메인 `STUDY_VWORLD_DOMAIN`이 필요합니다. 실제 키를 코드나 이슈·응답에 넣지 않습니다. 키가 없고 저장된 판정도 없으면 `WEATHER_REGION_NOT_CONFIGURED`(503)를 반환합니다. 브이월드의 인증·이용 데이터 설정에 문제가 있으면 조회 실패를 안내하며 검색 이름이나 좌표 반올림으로 조용히 대체하지 않습니다. 전국 시군구 목록의 일괄 사전 생성이나 사용자의 GPS를 자동 수집하는 기능은 포함하지 않습니다. Redis는 도입하지 않으며 기존 SQLite와 프로세스 내 키별 잠금을 사용합니다.

검증은 `test_neighborhoods.py`, `test_sigungu.py`에서 공식 코드별 공유, 동적 모델 응답 보존, 개인 조합 캐시·동시성·재시작, 주간 의류 목록, 날씨와 버전 변경, 10분 전 준비와 정규 일정 유지, 오류 재시도 제한 및 HTTP 흐름을 확인합니다. 실제 외부 API를 호출하지 않습니다.

공식 시군구 데이터: [국토교통부 행정구역도](https://www.data.go.kr/data/15059008/openapi.do), [브이월드 공식 데이터 API 예제](https://github.com/V-world/V-world_API_sample).

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
