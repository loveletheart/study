# 날씨 조회

국내 지역 검색, 오늘의 현재·일별·시간별 날씨, 오늘부터 7일 예보를 제공합니다. 외부 날씨 API는 Open-Meteo이며 인증키가 필요 없는 비상업적 학습용 공개 API를 사용합니다. 프론트 화면과 옷차림 추천 규칙은 다음 단계에서 연결합니다.

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
| `bootstrap.py` | 외부 클라이언트와 캐시를 Service에 연결 |

Router가 Service를 호출하면 Service는 WeatherProvider 인터페이스를 사용합니다. 실제 Open-Meteo 어댑터는 bootstrap에서 주입합니다. Domain과 Application은 FastAPI와 urllib을 import하지 않습니다. 날씨 조회에는 DB 저장이나 트랜잭션이 필요하지 않아 Repository와 Unit of Work를 만들지 않습니다.

## API 사용

루트의 `run.cmd` 또는 VS Code의 Ctrl+Shift+B로 실행한 뒤 http://127.0.0.1:8000/docs 의 weather 항목에서 호출합니다.

| API | 입력 | 결과 |
| --- | --- | --- |
| `GET /api/v1/weather/locations` | `query=서울`, `limit=5` | 국내 검색 후보와 위도·경도·지역 식별자 |
| `GET /api/v1/weather/today` | `latitude=37.5665`, `longitude=126.978` | 현재 날씨, 오늘 예보, 오늘 24시간 예보, 한글 요약 |
| `GET /api/v1/weather/weekly` | 같은 위도·경도 | 오늘부터 연속된 7일 예보 |

1. 지역 검색 결과에서 원하는 지역을 선택합니다. 이름이 같은 지역은 행정구역 정보로 구분합니다.
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
| `fetched_at` | 우리 서버가 응답을 받아온 시각. 제공사의 예보 발표 시각과 다름 |
| `provider`, `source_url` | 데이터 출처. 화면에도 Open-Meteo 출처 링크 표시 필요 |
| `units` | 기온 °C, 풍속 m/s, 강수량 mm, 적설량 cm, 강수확률 % |
| `current.time` | 모델 기반 현재 날씨의 기준 시각. 관측소 실측값을 뜻하지 않음 |
| `today`, `daily` | 날짜별 최저·최고·체감기온, 일교차, 최대 강수확률, 강수량·적설량, 최대 풍속, 자외선 지수, 날씨 코드와 한글 설명 |
| `hourly` | 오늘 00시~23시 기온·체감온도·강수확률·풍속·날씨 |
| `summary` | 오늘 예보 기반 한글 문장. 옷차림 추천 문장은 아직 포함하지 않음 |

일별 강수확률은 하루 중 **최대** 강수확률입니다. 비가 온다는 확정 표현으로 바꾸지 않습니다. 제공사가 선택 항목을 `null`로 반환하면 응답에도 `null`을 유지합니다. 프론트에서는 0이나 맑음으로 바꾸지 말고 정보 없음으로 표시해야 합니다. 알 수 없는 WMO 코드도 원래 코드와 함께 알 수 없는 날씨로 전달합니다.

## 캐시와 오류

- 기본 TTL은 600초입니다. 오늘과 주간 조회가 같은 좌표의 7일 예보를 공유합니다.
- 한국 시간 날짜를 캐시 키에 포함하므로 자정이 지나면 새 날짜의 예보를 조회합니다.
- 서버 프로세스별 메모리 캐시이며 재시작 시 비워집니다. 만료 데이터나 실패 응답은 정상 날씨로 반환하지 않습니다.
- `STUDY_WEATHER_CACHE_TTL_SECONDS=0`이면 캐시를 사용하지 않습니다.
- HTTP 요청은 기본 10초 타임아웃과 1MiB 응답 크기 제한을 사용합니다.

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
