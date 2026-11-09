# 국내 지역 검색 자료

이 폴더의 `kr_locations.json.gz`는 [GeoNames 국내 공개 목록](https://download.geonames.org/export/dump/KR.zip)에서 행정구역(A)과 도시·마을(P)을 추출한 부분 일치 검색용 자료입니다. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)에 따라 GeoNames 출처를 API 응답·화면·이 문서에 표시합니다. 원본 형식은 [GeoNames 설명](https://download.geonames.org/export/dump/readme.txt)을 참고하세요.

지역 ID와 위도·경도는 원본 값입니다. 한국어 표시 이름은 원본 이름이나 수록된 한국어 별칭에서 선택합니다. 같은 행정 계층에서 동일한 표시 이름을 가진 중복은 도시·행정구역 우선순위로 정리합니다. 국가 코드는 KR만 허용하고, 상위 지역은 원본 admin1~4 코드를 이용해 연결합니다. 행정코드로 좌표나 VWorld 시군구 코드를 추정하지 않습니다. 시설·산·하천 등은 제외합니다.

`manifest.json`에는 원본/생성 파일의 SHA-256, 생성 시각, 레코드 수와 형식 버전을 기록합니다. 자료는 GeoNames의 수록 범위와 갱신 시점에 따른 스냅샷이며 전국 모든 법정·행정동의 완전한 공식 목록을 보장하지 않습니다. 공식 시군구 판정은 기존 VWorld 점 포함 조회로 수행합니다.

프로젝트 루트에서 다음 명령으로 재생성한 뒤 서버를 재시작합니다.

```powershell
.\.venv\Scripts\python.exe backend/scripts/build_location_index.py --download
```

이미 내려받은 원본으로 재현하려면 `--source-zip 경로`를 사용합니다. 압축 데이터의 생성은 결정적이며 `manifest.json`의 생성 시각만 실행마다 달라집니다. 서버 실행·검색에서는 외부 다운로드를 하지 않습니다. 최초 검색 시 SQLite에 색인을 만들고, 다음 실행부터는 같은 버전을 재사용합니다. 기존 프로필·선택한 위치·추천 캐시는 이 색인 재생성에서 삭제하지 않습니다.
