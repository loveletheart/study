# 계정과 추천 프로필

이메일·비밀번호 로그인과 닉네임, 지역·추천 조건 저장을 제공합니다. `users`의 기존 계층과 역할별 파일을 유지하고 같은 `router.py`, `schemas.py`, `services.py`, `repositories.py`에 기능을 통합했습니다.

## API

모든 응답은 `code`, `message`, `data`, `details` 형식입니다.

| API | 역할 |
| --- | --- |
| `POST /api/v1/users/auth/register` | `name`, `email`, `password`로 가입 후 로그인 |
| `POST /api/v1/users/auth/login` | 이메일·비밀번호 확인 후 새 세션 발급 |
| `POST /api/v1/users/auth/logout` | 현재 브라우저 세션 폐기와 쿠키 삭제 |
| `GET /api/v1/users/me` | 본인 계정과 저장된 추천 프로필 |
| `PUT /api/v1/users/me/profile` | 닉네임·지역·추천 조건 저장 |
| `GET /api/v1/users/{user_id}` | 로그인한 본인의 기본 정보만 조회 |

변경 요청은 `X-Ondo-Request: 1` 헤더가 필요합니다. CORS 허용을 추가하지 않고 같은 출처의 화면이나 Vite 프록시를 사용합니다. 다른 출처의 `Sec-Fetch-Site: cross-site` 요청은 거부합니다. 계정 응답은 `Cache-Control: no-store`를 사용합니다.

프로필 예시:

```json
{
  "name": "온도친구",
  "location_id": 1835848,
  "preferences": {
    "cold_sensitivity": "cold",
    "style": "formal",
    "activity": "outdoor",
    "clothing_preference": "menswear",
    "avoid_items": ["sandals", "shorts"]
  }
}
```

`location_id`는 지역 검색에서 받은 국내 GeoNames 식별자입니다. 서버의 검증된 위치 목록에 없는 값은 거부합니다. API는 지역 미설정(`null`)도 허용하고, 화면의 설정 완료 버튼은 지역을 선택하도록 안내합니다. 저장 자체로 모델을 호출하지 않으며 화면이 저장 성공 후 추천을 조회합니다.

## 추천 입력

| 항목 | 선택값 |
| --- | --- |
| 체감 온도 | `normal`, `cold`, `warm` |
| 스타일 | `default`, `casual`, `formal` |
| 활동 | `daily`, `outdoor`, `active` |
| 선호 의류 | `any`, `menswear`, `womenswear` |
| 피할 의류 | `skirts`, `dresses`, `shorts`, `sandals`, `heels`, `sleeveless` 중 최대 6개 |

선호 의류는 성별 정체성 수집이 아닌 의류 유형에 대한 선택입니다. 피할 의류는 베스트 추천에서 제외하도록 모델에 요청합니다. 새 항목은 개인화 프롬프트와 캐시 키에도 포함하며, 제외 목록의 순서와 중복은 정규화합니다. 의류 제외를 의미 검증으로 강제하는 기능과 실제 생성 품질 평가는 별도 작업입니다.

닉네임·이메일·비밀번호·사용자 UUID·세션 토큰은 모델 입력에 포함하지 않습니다. 나이·키·몸무게·정확한 GPS·의류 치수 등 현재 추천에서 사용하지 않는 정보는 수집하지 않습니다.

로그인한 사용자가 화면에서 지역·취향을 바꾸면 계정에 저장합니다. 비로그인 설정은 브라우저의 `ondo.settings.v1`에 따로 유지하며, 로그아웃 시 해당 둘러보기 설정으로 돌아갑니다. 기본 추천·개인 추천 캐시는 계정 ID가 아닌 지역과 조건 조합으로 공유합니다.

## 인증 저장

비밀번호는 10~128자이며 공백을 제거하거나 문자를 잘라 저장하지 않습니다. 표준 라이브러리 scrypt(`N=32768`, `r=8`, `p=3`, 32MiB)와 각 비밀번호의 무작위 소금을 사용합니다. 이 조합은 [OWASP의 scrypt 설정](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt)에 해당합니다. 비밀번호 원문은 DB에 저장하지 않습니다.

세션은 무작위 토큰을 `HttpOnly`, `SameSite=Lax`, `/api/v1` 경로의 쿠키로 전달하고 서버에는 토큰의 SHA-256 해시만 저장합니다. 세션은 발급 후 7일에 만료하며 로그인할 때 현재 브라우저의 이전 세션을 교체하고 로그아웃할 때 서버 기록도 제거합니다. 프론트는 토큰이나 비밀번호를 브라우저 저장소에 기록하지 않습니다. 변경 요청의 전용 헤더는 [OWASP의 AJAX API CSRF 방어 방식](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html#employing-custom-request-headers-for-ajaxapi)을 사용합니다.

로컬 HTTP 개발에서는 Secure 쿠키가 꺼져 있습니다. HTTPS 환경에서는 서버 `.env`에 `STUDY_SESSION_COOKIE_SECURE=true`를 설정합니다. 별도 출처를 허용하는 배포 구성을 추가할 때에는 현재의 출처·쿠키 정책도 함께 조정해야 합니다.

인증 시도는 DB에 15분 단위로 기록하며 이메일별 10회, 접속 주소별 30회를 넘으면 `AUTH_RATE_LIMITED`(429)를 반환합니다. 버킷 키는 원문 이메일·주소 대신 해시를 저장합니다. 없는 계정과 비밀번호 오류는 같은 응답과 비밀번호 계산 비용을 사용합니다. 만료된 세션과 시도 제한 기록은 후속 인증 요청에서 정리합니다.

## DB 호환과 범위

서버 시작 시 기존 `users`를 보존하고 `user_credentials`, `user_sessions`, `user_recommendation_profiles`, `auth_rate_limits`를 추가합니다. 기존 사용자 등록 예제 API(`POST /users`, 이름·이메일만 받음)는 로그인 비밀번호를 만들지 않습니다. 이전 예제 데이터에 임의 비밀번호를 붙이거나 이메일만으로 계정을 가져오는 기능은 제공하지 않습니다. 새 계정은 회원가입 API로 등록합니다.

이메일 소유 확인, 비밀번호 재설정, 소셜 로그인과 계정 삭제는 아직 제공하지 않습니다. 추천 프로필은 서버에 저장되므로 같은 계정으로 다시 로그인하면 복원됩니다. 프로필 등록만으로 전국 배치를 예약하거나 주간 추천을 즉시 생성하지 않습니다. 새 개인 조건의 주간 결과는 다음 야간 배치에서 준비합니다.

## 검증

`tests/test_auth.py`는 임시 DB와 시험용 계정으로 해시 저장, 세션 회전·폐기·만료·재시작, CSRF 헤더, 본인 권한, 중복 가입, 이전 데이터 보존, 프로필 저장과 입력 거부, 요청 제한, 캐시 키·모델 입력을 확인합니다. 실제 운영 계정·DB와 외부 서비스는 사용하지 않습니다. 프론트 흐름은 `frontend/tests/auth.spec.js`에서 PC·모바일로 별도 검증합니다.
