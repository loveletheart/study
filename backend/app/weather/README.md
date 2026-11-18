# 날씨 조회

국내 지역 검색, 오늘의 현재·일별·시간별 날씨, 오늘부터 7일 예보를 제공합니다. 지역 검색은 GeoNames 국내 공개 목록을 SQLite에 색인해 사용하고, 날씨는 Open-Meteo 공개 API를 조회합니다. 프론트 화면과 옷차림 추천에 연결되어 있습니다.

## 계층과 요청 흐름

| 위치 | 역할 |
| --- | --- |
| `presentation/router.py` | 요청 검증과 공개 HTTP 오류·응답 처리 |
| `presentation/schemas.py` | Vue에서 사용할 요청·응답 계약 |
| `application/services.py` | 지역 검색, 오늘·주간 조회 절차 |
| `application/ports.py` | 외부 조회 인터페이스 |
| `application/dto.py` | 오늘 조회 결과와 지역 검색 결과 |
| `domain/models.py` | 날씨 객체, WMO 코드의 한글 설명, 기온 차이와 요약 |
| `infrastructure/open_meteo.py` | 외부 파라미터 구성, 단위·날짜·누락 검사, 도메인 변환 |
| `infrastructure/http_client.py` | HTTPS JSON 요청, 타임아웃과 응답 크기 제한 |
| `infrastructure/cache.py` | 최대 128개 항목의 프로세스 내 TTL 캐시 |
| `infrastructure/location_catalog.py` | 공개 지역 목록의 부분 검색·페이지 조회와 선택한 위치의 영속 저장 |
| `infrastructure/sigungu_resolver.py` | 검색 좌표를 브이월드 공식 시군구 경계에 조회하고 코드별 고정 대표점 저장 |
| `bootstrap.py` | 외부 클라이언트와 캐시를 Service에 연결 |

Router가 Service를 호출하면 Service는 WeatherProvider 인터페이스를 사용합니다. 실제 Open-Meteo 어댑터는 bootstrap에서 주입합니다. Domain과 Application은 FastAPI와 urllib을 import하지 않습니다. 예보 조회 자체에는 DB 트랜잭션이 없으며, 지역 검색 결과는 별도의 LocationCatalog 계약으로 SQLite에 저장해 동네별 추천이 검증한 대표 좌표를 재사용할 수 있게 합니다. 지역 `id`는 GeoNames 식별자이며 공식 한국 행정동 코드가 아닙니다.

옷차림의 시군구 공유는 검색 좌표를 브이월드 `LT_C_ADSIGG_INFO`에 조회한 `sig_cd`로 결정합니다. 같은 시군구 코드는 최초로 확인한 내부 좌표를 고정 대표점으로 사용하며 단순 반올림이나 이름 유사도로 묶지 않습니다. 시군구 판정은 키가 필요한 별도 기능이고, 기존 좌표 기반 날씨 API는 브이월드 키 없이 그대로 사용할 수 있습니다.

## API 사용

루트의 `run.cmd` 또는 VS Code의 Ctrl+Shift+B로 실행한 뒤 http://127.0.0.1:8000/docs 의 weather 항목에서 호출합니다.

| API | 입력 | 결과 |
| --- | --- | --- |
| `GET /api/v1/weather/locations` | `query=서울`, `limit=5` | 국내 검색 후보와 위도·경도·지역 식별자 |
| `GET /api/v1/weather/today` | `latitude=37.5665`, `longitude=126.978` | 현재 날씨, 오늘 예보, 오늘 24시간 예보, 한글 요약 |
| `GET /api/v1/weather/weekly` | 같은 위도·경도 | 오늘부터 연속된 7일 예보 |

1. 지역 검색 결과에서 원하는 지역을 선택합니다. 이름이 같은 지역은 행정구역 정보로 구분합니다.
   `서울`은 지역명·별칭·상위 행정구역에 서울이 포함된 지역을 찾습니다. 고정된 도시 이름 치환이나 외부 API의 앞부분 일치에 의존하지 않습니다. `서울 강남`은 두 단어가 모두 포함된 지역을 찾으며 `경기 광주`로 동명 지역을 구분할 수 있습니다. `%서울%`로 입력해도 같은 포함 검색을 수행하지만 `%`를 입력할 필요는 없습니다. 도시·행정구역을 마을보다 먼저 보여주고 전체 결과를 페이지로 제공합니다. 자료에 수록되지 않은 동네·도로명·상세 주소는 검색되지 않을 수 있습니다.
2. 선택한 결과의 `latitude`와 `longitude`를 오늘·주간 조회에 전달합니다.
3. 좌표를 생략하면 특정 지역을 임의로 선택하지 않고 `422`를 반환합니다.

PowerShell에서도 호출할 수 있습니다.

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/weather/locations?query=Seoul"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/weather/today?latitude=37.5665&longitude=126.978"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/weather/weekly?latitude=37.5665&longitude=126.978"
```

## 응답에서 확인할 정보

모든 응답은 `code`, `message`, `data`, `details` 형식입니다. 성공 시 `code`는 `SUCCESS`이고 아래 날씨 필드는 `data` 안에 있습니다. 예: `data.current.temperature_c`, `data.daily`, `data.locations`. 실패 시 `data`는 `null`입니다.

| 필드 | 의미 |
| --- | --- |
| `coordinates` | 사용자가 요청한 좌표. 제공사의 실제 예보 격자 중심과 다를 수 있음 |
| `timezone` | `Asia/Seoul`. 국내 서비스이므로 모든 날짜를 한국 시간으로 해석 |
| `fetched_at` | 우리 서버가 응답을 받아온 시각. 이전 예보를 사용해도 원래 값 유지 |
| `is_stale` | 외부 예보 갱신 장애로 마지막 정상 예보를 제공했으면 `true` |
| `provider`, `source_url` | 데이터 출처. 화면에도 Open-Meteo 출처 링크 표시 필요 |
| `units` | 기온 °C, 풍속 m/s, 강수량 mm, 적설량 cm, 강수확률 % |
| `current.time` | 모델 기반 현재 날씨의 기준 시각. 관측소 실측값을 뜻하지 않음 |
| `today`, `daily` | 날짜별 최저·최고·체감기온, 일교차, 최대 강수확률, 강수량·적설량, 최대 풍속, 자외선 지수, 날씨 코드와 한글 설명 |
| `hourly` | 오늘 00시~23시 기온·체감온도·강수확률·풍속·날씨 |
| `summary` | 오늘 예보 기반 한글 문장. 옷차림 추천 문장은 아직 포함하지 않음 |

일별 강수확률은 하루 중 **최대** 강수확률입니다. 비가 온다는 확정 표현으로 바꾸지 않습니다. 제공사가 선택 항목을 `null`로 반환하면 응답에도 `null`을 유지합니다. 프론트에서는 0이나 맑음으로 바꾸지 말고 정보 없음으로 표시해야 합니다. 알 수 없는 WMO 코드도 원래 코드와 함께 알 수 없는 날씨로 전달합니다.

## 캐시와 오류

지역 검색은 포함된 [GeoNames 국내 자료](infrastructure/data/README.md)를 최초 한 번 DB에 색인한 후 외부 API 호출 없이 수행합니다. 현재 묶음은 68,091개 지역이며 원본 ID·좌표와 상위 행정구역 정보를 사용합니다. `search_text LIKE '%검색어%'`를 매개변수 바인딩과 와일드카드 이스케이프를 사용해 실행합니다. 공백으로 나눈 검색어는 AND 조건입니다. `limit`은 1~50(기본 5), `offset`은 0~1000000이며 응답에 `total`, `offset`, `limit`, `has_more`를 추가했습니다. 클라이언트는 `has_more`가 참이면 `offset + locations.length`로 다음 페이지를 조회합니다. 결과가 비어도 정상 200입니다.

원본 자료의 갱신은 다운로드 스크립트로 명시적으로 수행합니다. 서버는 같은 버전의 DB 색인을 재사용하고 자료 버전이 바뀌면 검색 색인만 교체합니다. 기존 사용자 프로필·위치 저장·추천 결과는 삭제하지 않습니다. GeoNames 행정코드는 검색 계층 구분에만 쓰며 공식 VWorld 시군구 코드로 간주하지 않습니다.

Redis를 실행한 뒤 프로젝트 루트의 `.env`에 설정합니다.

```dotenv
STUDY_WEATHER_REDIS_URL=redis://127.0.0.1:6379/0
STUDY_WEATHER_CACHE_TTL_SECONDS=3600
STUDY_WEATHER_CACHE_STALE_MAX_SECONDS=10800
```

- 오늘·주간 날씨와 대표 좌표가 같은 시군구 추천은 제공사·좌표·한국 날짜로 구분한 7일 예보를 공유합니다. Redis URL이 없으면 프로세스 메모리 캐시를 사용하고, `STUDY_WEATHER_CACHE_TTL_SECONDS=0`이면 두 캐시 모두 비활성화합니다.
- 두 캐시 모두 조회 후 기본 1시간 동안 최신으로 판단하며, 이전 예보는 최대 3시간까지 재사용할 수 있습니다. 같은 프로세스의 동시 갱신은 한 번으로 합칩니다. Redis에서는 프로세스 간 갱신도 잠금으로 조율하고 제공사 오류를 5초 동안 공유합니다.
- 시간 초과, 연결 장애, 요청 한도 초과 시 같은 한국 날짜의 보관 중인 마지막 정상 예보를 날씨 화면에 반환할 수 있습니다. 잘못된 데이터나 날짜에는 기존 오류를 반환합니다. 옷차림 갱신은 이전 예보를 갱신 성공으로 기록하지 않습니다.
- Redis 연결과 명령의 대기 제한은 각 1초입니다. Redis 조회나 잠금 획득 중 연결 오류가 발생하면 프로세스 메모리 캐시를 사용합니다. 메모리에 저장된 예보가 최신이면 그대로 사용하고, 갱신이 필요하면 같은 좌표의 동시 요청을 모아 Open-Meteo에 한 번 요청합니다. Redis가 복구되면 공유 캐시를 다시 우선 사용합니다. FastAPI 재시작 후에도 Redis에 남은 예보를 사용합니다. Redis 재시작까지 보존하려면 Redis의 영속화 옵션을 설정합니다. ([Redis 영속화 안내](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/))
- HTTP 요청은 기본 10초 타임아웃과 1MiB 응답 크기 제한을 사용합니다.

실제 Redis에서 새 클라이언트가 기존 예보를 재사용하는지 검증하려면 `STUDY_TEST_REDIS_URL`에 테스트용 Redis 주소를 설정하고 `backend`에서 가상환경 Python으로 `python -m unittest tests.test_weather_redis`를 실행합니다.

| 상태 | 의미 |
| --- | --- |
| `200` | 정상 조회. 검색 결과가 없으면 `locations: []` |
| `422` | 잘못된 좌표, 너무 짧은 검색어, 검색 개수 등 입력 오류 |
| `502` | 제공사의 오류 응답, 잘못된 JSON, 누락된 필수 데이터, 잘못된 단위·날짜 |
| `503` | 연결 실패, 제공사 장애, 요청 한도 초과 |
| `504` | 제공사 응답 시간 초과 |

## Swagger와 오류 코드

`/docs`에서 API별 사용 방법과 요청·응답 필드 설명을 볼 수 있습니다. 오류도 공통 `code`, `message`, `data`, `details` 형식이며, 같은 HTTP 503도 `WEATHER_UNAVAILABLE`과 `WEATHER_RATE_LIMITED`로 구분합니다. 예시 선택 목록에서 각 오류를 확인할 수 있습니다.

- `WEATHER_INVALID_QUERY`: 날씨 조회 조건 오류(422)
- `WEATHER_INVALID_RESPONSE`: 제공사 응답 형식·단위·날짜 또는 데이터 오류(502)
- `WEATHER_UNAVAILABLE`: 제공사 연결 실패·서버 오류(503)
- `WEATHER_RATE_LIMITED`: 제공사 호출 한도 초과(503)
- `WEATHER_TIMEOUT`: 제공사 응답 제한 시간 초과(504)
- `COMMON_INVALID_REQUEST`: FastAPI 입력 검증 오류(422)

코드 정의와 기본 메시지는 `common/errors/codes.py`가 관리하며 라우터에서 HTTP 오류로 개별 변환하지 않습니다. 자세한 규칙은 [공통 오류 문서](../common/errors/README.md)를 참고하세요.

## 검증과 공식 문서

프로젝트 루트에서 `run.cmd -Test`를 실행합니다. 날씨 테스트는 합성 응답으로 단위·날짜·타임존, 누락된 값, 캐시 만료·자정 갱신, 오류 응답을 검증하며 외부 API를 호출하지 않습니다. 실제 통신 확인은 네트워크가 허용되는 환경에서 Swagger로 수행해야 합니다.

- 예보: https://open-meteo.com/en/docs
- 지역 검색: https://open-meteo.com/en/docs/geocoding-api
- 이용 범위와 출처 표기: https://open-meteo.com/en/terms

공개 무료 API는 비상업적 사용을 전제로 합니다. 상업 서비스로 전환할 때는 제공사의 이용 조건과 요금제를 확인해야 합니다.
