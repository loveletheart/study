"""검색에서 검증한 지역 식별자와 대표 좌표의 영속 목록."""


# 표준 라이브러리
from contextlib import closing
from pathlib import Path
from functools import lru_cache
from threading import Lock
import gzip
import hashlib
import json
import unicodedata

# 외부 라이브러리
from pydantic import TypeAdapter, ValidationError

# 프로젝트 모듈
from app.common.database import connect_database
from app.weather.application.exceptions import InvalidWeatherQueryError
from app.weather.application.dto import LocationSearchResult
from app.weather.domain.models import Coordinates
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


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _like_literal(value: str) -> str:
    """와일드카드는 서버에서 붙이고 사용자 입력의 특수 문자는 문자 그대로 비교한다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@lru_cache(maxsize=1)
def _bundled_regions(digest: str) -> tuple[dict, ...]:
    path = Path(__file__).with_name("data") / "kr_locations.json.gz"
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("국내 지역 검색 자료의 해시가 일치하지 않습니다.")
    return tuple(json.loads(gzip.decompress(data)))


class SQLiteLocationSearch:
    def __init__(self, database_path: Path, records: tuple[dict, ...] | None = None, revision: str | None = None) -> None:
        """공개 지역 목록을 처음 검색할 때 한 번 색인한다. 계정·기존 위치 목록은 보존한다."""
        self._path = database_path
        self._records = records
        self._revision = revision
        self._lock = Lock()
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            manifest = json.loads((Path(__file__).with_name("data") / "manifest.json").read_text(encoding="utf-8")) if self._records is None else None
            revision = self._revision or (f"{manifest['format_version']}:{manifest['bundle_sha256']}" if manifest else "test")
            with closing(connect_database(self._path)) as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS weather_location_search (id INTEGER PRIMARY KEY, name_search TEXT NOT NULL, search_text TEXT NOT NULL, priority INTEGER NOT NULL, population INTEGER NOT NULL, payload BLOB NOT NULL)")
                connection.execute("CREATE TABLE IF NOT EXISTS weather_location_search_version (id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT NOT NULL)")
                saved = connection.execute("SELECT revision FROM weather_location_search_version WHERE id=1").fetchone()
                if saved is None or saved["revision"] != revision:
                    records = self._records if self._records is not None else _bundled_regions(manifest["bundle_sha256"])
                    def values():
                        for record in records:
                            location = LOCATION_ADAPTER.validate_python(record["location"])
                            Coordinates(location.latitude, location.longitude)
                            if location.country_code != "KR" or location.id <= 0:
                                raise ValueError("국내 지역 색인에 허용되지 않는 위치입니다.")
                            yield (location.id, _normalize(record["name_search"]), _normalize(record["search_text"]), record["priority"], record["population"], LOCATION_ADAPTER.dump_json(location))
                    connection.execute("DELETE FROM weather_location_search")
                    connection.executemany("INSERT INTO weather_location_search VALUES (?, ?, ?, ?, ?, ?)", values())
                    connection.execute("INSERT INTO weather_location_search_version VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision", (revision,))
            self._ready = True

    def search(self, query: str, limit: int, offset: int) -> LocationSearchResult:
        query = _normalize(query.strip().strip("%").strip())
        if not 2 <= len(query) <= 100 or not 1 <= limit <= 50 or not 0 <= offset <= 1000000:
            raise InvalidWeatherQueryError("두 글자 이상의 지역명으로 검색해 주세요.")
        self._ensure()
        tokens = list(dict.fromkeys(query.split()))
        where = " AND ".join("search_text LIKE ? ESCAPE '\\'" for _ in tokens)
        parameters = [f"%{_like_literal(token)}%" for token in tokens]
        with closing(connect_database(self._path)) as connection, connection:
            total = connection.execute(f"SELECT COUNT(*) FROM weather_location_search WHERE {where}", parameters).fetchone()[0]
            rows = connection.execute(
                f"SELECT payload FROM weather_location_search WHERE {where} ORDER BY priority, CASE WHEN name_search=? THEN 0 WHEN name_search LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END, population DESC, name_search, id LIMIT ? OFFSET ?",
                (*parameters, query, _like_literal(query) + "%", limit, offset),
            ).fetchall()
        return LocationSearchResult(tuple(LOCATION_ADAPTER.validate_json(row["payload"]) for row in rows), "GeoNames · CC BY 4.0 · https://www.geonames.org/", total, offset, limit, offset + len(rows) < total)
