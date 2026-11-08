"""검색에서 검증한 지역 식별자와 대표 좌표의 영속 목록."""


# 표준 라이브러리
from contextlib import closing
from pathlib import Path

# 외부 라이브러리
from pydantic import TypeAdapter, ValidationError

# 프로젝트 모듈
from app.common.database import connect_database
from app.weather.application.exceptions import InvalidWeatherQueryError
from app.weather.domain.models import Location


# JSON 변환·검증
LOCATION_ADAPTER = TypeAdapter(Location)


# 지역 검색 결과 저장소
class SQLiteLocationCatalog:
    def __init__(self, database_path: Path) -> None:
        """지역 목록 저장 테이블 준비"""
        self._database_path = database_path
        with closing(connect_database(database_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS weather_locations (id INTEGER PRIMARY KEY, payload BLOB NOT NULL)",
            )

    def save(self, locations: tuple[Location, ...]) -> None:
        """외부 검색의 국내 지역만 저장하고 동일 식별자는 최신 대표 좌표 사용"""
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.executemany(
                "INSERT INTO weather_locations (id, payload) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                [(location.id, LOCATION_ADAPTER.dump_json(location)) for location in locations
                 if location.country_code == "KR" and location.id > 0],
            )

    def get(self, location_id: int) -> Location:
        """알 수 없는 식별자는 임의 좌표로 대체하지 않고 지역 검색 안내"""
        with closing(connect_database(self._database_path)) as connection:
            row = connection.execute("SELECT payload FROM weather_locations WHERE id=?", (location_id,)).fetchone()
        if row is not None:
            try:
                location = LOCATION_ADAPTER.validate_json(row["payload"])
                if location.id == location_id and location.country_code == "KR":
                    return location
            except ValidationError:
                pass
        raise InvalidWeatherQueryError("지역 검색 API에서 반환된 국내 지역 식별자를 선택해 주세요.")
