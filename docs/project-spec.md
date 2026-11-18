# 온도 프로젝트 명세

2026년 11월 16일 기준 `dev`의 구현을 정리했습니다. [기준 커밋 `9670881`](https://github.com/loveletheart/study/commit/9670881abe0f8074c6d596a372ac17cee15f962e) · [프로젝트 README](../README.md)

## 기능

- 저장한 지역을 복원하고, 저장값이 없으면 서울특별시 중구를 검색합니다. 지역을 바꾸면 현재·시간별 날씨, 7일 예보와 옷차림을 확인할 수 있습니다.
- 오늘과 주간의 선택 날짜에서 베스트·워스트 옷차림을 함께 보여줍니다. 넓은 화면에서는 나란히, 좁은 화면에서는 연달아 표시합니다. 긴 설명은 요약과 상세로 나눕니다.
- 체감 추위, 스타일, 활동, 선호 의류와 피할 의류를 요청에 반영합니다. 로그인하면 지역과 취향을 계정에 저장하고, 비로그인 설정은 브라우저에 따로 저장합니다.
- 로그인한 사용자는 생성 기록이 있는 추천을 신고하고 수정안을 검수할 수 있습니다. 사용자가 승인한 자기 자료를 내보낼 수 있습니다.
- 실제 상품 이미지, 인기 순위, 검증된 의류 카탈로그, 비밀번호 재설정과 소셜 로그인은 후속 범위입니다.

[프론트엔드 개발과 검증](../frontend/README.md) · [피드백 사용법](../FEEDBACK.md)

## API

업무 API는 `/api/v1` 아래에 있습니다. 응답은 `code`, `message`, `data`, `details` 형식이고, 실패 응답은 `data=null`입니다. 서버 실행 후 전체 필드와 오류 코드는 [Swagger](http://127.0.0.1:8000/docs)와 [OpenAPI 명세](http://127.0.0.1:8000/openapi.json)에서 확인합니다.

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/users/auth/register`, `/users/auth/login`, `/users/auth/logout` | 가입 및 세션 발급, 로그인, 세션 폐기 |
| GET / PUT | `/users/me` / `/users/me/profile` | 본인 계정과 추천 프로필 조회·저장 |
| POST / GET | `/users` / `/users/{user_id}` | 학습용 사용자 등록과 로그인한 본인의 정보 조회 |
| GET | `/weather/locations` | 국내 지역 검색. `limit` 1~50, `offset`으로 더 보기 |
| GET | `/weather/today`, `/weather/weekly` | 좌표 기준 오늘과 7일 날씨 |
| GET | `/outfits/today`, `/outfits/weekly` | 좌표 기준 오늘 추천과 저장된 주간 추천 |
| GET | `/outfits/regions/{location_id}/today`, `/outfits/regions/{location_id}/weekly` | 시군구 공통 추천 및 개인화 |
| POST / GET | `/outfit-feedback` | 본인 신고 등록 및 목록 조회 |
| GET / PUT | `/outfit-feedback/{identifier}` | 본인 신고 상세 조회 및 수정 |
| POST | `/outfit-feedback/{identifier}/approve`, `/outfit-feedback/{identifier}/reject` | 수정안 승인·거절 |
| GET | `/outfit-feedback/export` | 본인이 승인한 수정 정답 내보내기 |

보호 API는 `ondo_session` 쿠키를 사용합니다. 가입·로그인·로그아웃·프로필 변경·피드백 변경 요청에는 `X-Ondo-Request: 1` 헤더가 필요합니다. 피드백 생성은 실제 추천의 `generation_id`와 날짜를 참조하며, 편집·검수는 현재 `revision`이 일치할 때 반영합니다.

지역 추천의 `location_id`는 검색 결과 식별자입니다. 공식 시군구는 응답의 `region.code`에서 확인합니다. 지역 추천 요청의 개인 조건은 다음과 같습니다.

| 필드 | 선택값 | 기본값 |
| --- | --- | --- |
| `cold_sensitivity` | `normal`, `cold`, `warm` | `normal` |
| `style` | `default`, `casual`, `formal` | `default` |
| `activity` | `daily`, `outdoor`, `active` | `daily` |
| `clothing_preference` | `any`, `menswear`, `womenswear` | `any` |
| `avoid_items` | `skirts`, `dresses`, `shorts`, `sandals`, `heels`, `sleeveless`. 같은 이름의 쿼리로 반복 전달 | 빈 목록 |

추천 결과는 `best`와 `worst`에 의류 구성을, `reasons`와 `avoid_reasons`에 각각의 이유를 담습니다. 공통 추천의 제공사·전환 여부·생성 ID는 `engine`, 별도로 생성된 개인 추천의 정보는 `personalization.engine`에서 확인합니다. 주간은 `forecast_start_date`로 기준 날짜를 확인합니다.

[사용자 API](../backend/app/users/README.md) · [날씨 API](../backend/app/weather/README.md) · [옷차림 API](../backend/app/outfits/README.md) · [오류 코드](../backend/app/common/errors/codes.py)

## 데이터

SQLite 기본 경로는 루트의 `study.db`입니다. 데이터를 사용하는 기능이 초기화될 때 일부 테이블을 생성합니다.

| 영역 | 저장 내용 |
| --- | --- |
| 계정 | `users`, `user_credentials`, `user_sessions`, `user_recommendation_profiles`, `auth_rate_limits`에 기본 정보, 비밀번호 해시, 세션, 개인 조건과 시도 제한 저장 |
| 지역 | `weather_locations`, `weather_location_search`, `weather_location_search_version`에 검색 후보와 인덱스 저장. `weather_sigungu_points`, `weather_sigungu_regions`에 공식 판정과 대표점 저장 |
| 추천 | `outfit_result_cache`에 공통 추천, `outfit_personal_results`와 `outfit_personal_targets`에 개인화 결과와 사전 생성 대상, `outfit_weekly_batch_runs`와 `outfit_weekly_batch_targets`에 당일 실행과 지역별 진행 상태 저장 |
| 피드백 | `outfit_generations`에 실제 생성 입출력과 실패 유형, `outfit_feedback`에 신고와 수정안, `outfit_feedback_history`에 변경 이력 저장 |

비밀번호는 계정별 무작위 솔트를 사용하는 scrypt 해시로 저장합니다. 세션용 무작위 토큰은 쿠키로 전달하고 DB에는 SHA-256 해시, 절대 만료 시각과 마지막 인증 활동 시각을 저장합니다. 구버전 세션의 마지막 활동 시각은 기존 7일 만료에서 발급 시각을 복원해 채웁니다. 기존 계정과 프로필은 보존합니다.

공통 추천은 모델·프롬프트 설정 범위, 추천 종류와 대표 좌표로 구분합니다. 개인화 결과는 시군구·조건 조합과 공통 생성 버전을 기준으로 재사용합니다. 피드백은 소유자·생성 ID·날짜를 기준으로 중복을 제한하고, 추천 캐시는 사용자 ID와 독립적으로 공유합니다.

[계정 스키마](../backend/app/users/infrastructure/models.py) · [캐시 저장](../backend/app/outfits/infrastructure/cache.py) · [피드백 저장](../backend/app/outfits/infrastructure/feedback.py)

## 갱신과 운영

| 대상 | 기본 동작 |
| --- | --- |
| 오늘 공통 추천 | 최근 조회 대상을 약 1시간마다 확인하고 예보 입력이 바뀌면 재생성합니다. 첫 조회, 한국 날짜 변경 또는 마지막 정상 확인 후 3시간 초과 시 생성이 필요합니다. |
| 오늘 개인화 | 최근 요청 조건은 공통 갱신 예정 10분 전부터 준비합니다. 최초 조합은 요청에서 생성할 수 있습니다. |
| 주간 추천 | 한국 시간 01:00부터 당일 배치를 시작합니다. 서버가 늦게 켜져도 당일 작업을 확인하고, 중단되면 남은 지역부터 이어서 처리합니다. 조회 시 모델을 호출하지 않으며, 결과가 없으면 `OUTFIT_WEEKLY_NOT_READY`를 반환합니다. 이전 결과는 기본 최대 48시간까지 사용합니다. |
| 시군구 판정 | VWorld 조회 결과를 저장하고 기본 24시간 후 재확인합니다. 조회 장애 시 같은 좌표의 이전 정상 판정을 재사용할 수 있습니다. |
| 세션 | 인증 활동이 없으면 30분, 계속 사용해도 발급 후 24시간에 만료합니다. 보호 API만 마지막 활동을 갱신하며, 화면은 만료 확인 후 재로그인을 안내합니다. |

- Ollama가 정상 응답을 반환하면 로컬 결과를 사용합니다. 자동 전환을 켜면 로컬 요청당 대기 제한은 기본 20초이고, 타임아웃 시 한 번 더 요청합니다. 형식·날짜·품질·베스트/워스트 중복 오류도 한 번의 수정 재시도 예산을 공유합니다. 연결 거부·모델 없음·미설정은 적격 오류가 발생한 시점에 Gemini로 넘어갑니다.
- `WEATHER_REGION_NOT_CONFIGURED`는 저장된 해당 좌표 판정과 VWorld 키가 없어 시군구 조회에서 중단됐다는 뜻입니다. Gemini로 넘어갔는지는 서버의 전환 로그와 응답 코드로 확인합니다. `OUTFIT_CLOUD_*`는 Gemini 설정·연결·인증·한도를 확인할 때 사용합니다.
- `AUTH_SESSION_EXPIRED`는 서버에 제시된 세션이 만료됐을 때 반환합니다. 로그아웃은 서버 세션과 쿠키를 함께 폐기합니다. HTTPS에서 쿠키의 `Secure`를 적용하며, 앱에 HTTP를 전달하는 HTTPS 프록시 뒤에서는 `STUDY_SESSION_COOKIE_SECURE=true`로 강제할 수 있습니다.

시작 시간과 갱신 예정 시점은 처리 완료 시각을 보장하지 않습니다. 설정 키와 기본값, 실행과 테스트 명령은 [프로젝트 README](../README.md) 및 [추천 운영 안내](../backend/app/outfits/README.md)에서 확인할 수 있습니다.

## 구조와 설계

| 구성 | 책임 |
| --- | --- |
| Vue 3와 Vite | 지역·취향·날짜 선택, 비교 화면, 계정·피드백 UI. 개발 시 `/api`를 FastAPI로 프록시 |
| FastAPI | 정적 빌드가 있을 경우 `/app/` 제공. 사용자·날씨·옷차림 라우터 등록 |
| `presentation` | 입력 검증, 인증·요청 의존성, 응답 직렬화. 옷차림과 피드백은 하나의 라우터 사용 |
| `application` | 날씨·추천 조회 흐름, 생성·전환 정책, 인증의 업무 절차와 포트 |
| `domain` | 날씨·의류·선택 조건, 추천 결과 구성, 품질 규칙 |
| `infrastructure` | Open-Meteo·VWorld·Ollama·Gemini 연결, SQLite 저장, 갱신과 배치 실행 |
| `bootstrap.py` | 설정에 맞춰 추천기·캐시·서비스를 구성하고 주입 |

추천은 서버가 확보한 원본 예보로 모델에 요청합니다. 응답의 날짜·스키마·의류 구성 등을 검증하고, 서버의 원본 예보를 결합해 저장합니다. 피드백에는 변경할 수 없는 원본 생성 기록을 남기며, 승인된 수정안은 원본과 별도로 보존합니다.

- [#19 Vue MVP·계정·피드백](https://github.com/loveletheart/study/pull/19)
- [#18 추천 복구와 라우터 통합](https://github.com/loveletheart/study/pull/18)
- [#22 베스트·워스트 비교와 기본 지역](https://github.com/loveletheart/study/pull/22)
- [#25 로그인 세션 만료](https://github.com/loveletheart/study/pull/25)
