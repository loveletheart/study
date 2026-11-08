"""공통·개인 추천과 생성 대상을 SQLite에 보관한다."""


# 표준 라이브러리
import logging
import hashlib
import json
from _thread import LockType
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Event, Lock
from time import perf_counter
from weakref import WeakValueDictionary
from typing import Literal, overload
from dataclasses import asdict
from uuid import uuid4

# 외부 라이브러리
from pydantic import TypeAdapter, ValidationError

# 프로젝트 모듈
from app.common.database import connect_database
from app.outfits.application.dto import (
    TodayOutfitResult,
    WeeklyOutfitResult,
    GeneratedOutfits,
    PersonalizedOutfits,
)
from app.outfits.application.exceptions import (
    OutfitForecastError,
    WeeklyOutfitNotReadyError,
    OutfitLlmResponseError,
)
from app.outfits.application.services import OutfitService
from app.weather.domain.models import KST
from app.outfits.application.ports import OutfitPersonalizer
from app.outfits.domain.models import OutfitPreferences
from app.weather.application.ports import LocationReader


# 로그
logger = logging.getLogger(__name__)


# 캐시 키와 결과 타입
OutfitResult = TodayOutfitResult | WeeklyOutfitResult
CacheKey = tuple[str, str, float, float]


# JSON 변환·검증
TODAY_ADAPTER = TypeAdapter(TodayOutfitResult)
WEEKLY_ADAPTER = TypeAdapter(WeeklyOutfitResult)

RESULT_ADAPTERS: dict[str, TypeAdapter[TodayOutfitResult] | TypeAdapter[WeeklyOutfitResult]] = {
    "today": TODAY_ADAPTER, "weekly": WEEKLY_ADAPTER,
}

PERSONAL_ADAPTER = TypeAdapter(PersonalizedOutfits)
PREFERENCES_ADAPTER = TypeAdapter(OutfitPreferences)


# 테이블 생성 SQL
CREATE_CACHE_TABLE = """
CREATE TABLE IF NOT EXISTS outfit_result_cache (
    scope TEXT NOT NULL,
    kind TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    requested_at REAL NOT NULL,
    attempted_at REAL NOT NULL DEFAULT 0,
    prepared_for REAL NOT NULL DEFAULT 0,
    updated_at REAL,
    payload BLOB,
    PRIMARY KEY (scope, kind, latitude, longitude)
)
"""


# 결과 직렬화
def _dump_result(result: OutfitResult) -> bytes:
    """결과의 실제 타입에 맞는 어댑터로 직렬화한다."""
    if isinstance(result, TodayOutfitResult):
        return TODAY_ADAPTER.dump_json(result)
    return WEEKLY_ADAPTER.dump_json(result)


# 공통 추천 캐시
class CachedOutfitService:
    def __init__(
        self, database_path: Path, scope: str, service_factory: Callable[[], OutfitService],
        refresh_seconds: float = 3600, clock: Callable[[], datetime] | None = None,
        reuse_unchanged_weather: bool = False,
        max_entries: int = 128,
        weekly_batch_only: bool = False, weekly_batch_hour: int = 1, weekly_max_age_seconds: float = 172800,
    ) -> None:
        """저장 경로와 갱신 주기를 설정한다."""
        self._database_path = database_path
        self._scope = scope
        self._service_factory = service_factory
        self._refresh_seconds = refresh_seconds
        self._reuse_unchanged_weather = reuse_unchanged_weather
        self._max_entries = max_entries
        self._weekly_batch_only = weekly_batch_only
        self._weekly_batch_hour = weekly_batch_hour
        self._weekly_max_age_seconds = weekly_max_age_seconds
        self._clock = clock or (lambda: datetime.now(KST))
        self._generation_locks: WeakValueDictionary[CacheKey, LockType] = WeakValueDictionary()
        self._generation_locks_guard = Lock()
        with closing(connect_database(database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(CREATE_CACHE_TABLE)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(outfit_result_cache)")}
            if "requested_at" not in columns:
                connection.execute(
                    "ALTER TABLE outfit_result_cache ADD COLUMN requested_at REAL NOT NULL DEFAULT 0",
                )
                connection.execute(
                    "UPDATE outfit_result_cache SET requested_at=COALESCE(updated_at, attempted_at, 0)",
                )
            if "prepared_for" not in columns:
                connection.execute("ALTER TABLE outfit_result_cache ADD COLUMN prepared_for REAL NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outfit_weekly_batch_runs "
                "(scope TEXT NOT NULL, run_date TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, "
                "status TEXT NOT NULL, PRIMARY KEY(scope, run_date))",
            )

    def get_today(self, latitude: float, longitude: float) -> TodayOutfitResult:
        """오늘 추천을 재사용하고 저장된 결과가 없을 때만 생성한다."""
        return self._get("today", latitude, longitude)

    def get_weekly(self, latitude: float, longitude: float) -> WeeklyOutfitResult:
        """주간 추천을 재사용하고 저장된 결과가 없을 때만 생성한다."""
        return self._get("weekly", latitude, longitude)

    def get_region_today(self, location_id: int, latitude: float, longitude: float) -> TodayOutfitResult:
        """지역 식별자·대표 좌표별 공통 오늘 추천 조회"""
        return self._get("today", latitude, longitude, location_id)

    def get_region_weekly(self, location_id: int, latitude: float, longitude: float) -> WeeklyOutfitResult:
        """지역 식별자·대표 좌표별 공통 주간 추천 조회"""
        return self._get("weekly", latitude, longitude, location_id)

    def _key(self, kind: str, latitude: float, longitude: float) -> CacheKey:
        """제공사 설정·조회 종류·정확한 좌표로 저장 키 구성"""
        return self._scope, kind, latitude, longitude

    def _lock_for(self, key: CacheKey) -> LockType:
        """동일 키의 생성 잠금을 공유하고 사용자·대기자가 없으면 자동 회수"""
        with self._generation_locks_guard:
            generation_lock = self._generation_locks.get(key)
            if generation_lock is None:
                generation_lock = Lock()
                self._generation_locks[key] = generation_lock
            return generation_lock

    @overload
    def _get(
        self, kind: Literal["today"], latitude: float, longitude: float, location_id: int | None = None,
    ) -> TodayOutfitResult: ...

    @overload
    def _get(
        self, kind: Literal["weekly"], latitude: float, longitude: float, location_id: int | None = None,
    ) -> WeeklyOutfitResult: ...

    def _get(
        self, kind: Literal["today", "weekly"], latitude: float, longitude: float, location_id: int | None = None,
    ) -> OutfitResult:
        """동시 최초 요청은 한 번만 생성하고 갱신 중에는 기존 결과 제공"""
        cache_kind = kind if location_id is None else f"region:{location_id}:{kind}"
        key = self._key(cache_kind, latitude, longitude)
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "INSERT INTO outfit_result_cache (scope, kind, latitude, longitude, requested_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (scope, kind, latitude, longitude) DO UPDATE SET requested_at=excluded.requested_at",
                (*key, self._clock().timestamp()),
            )
            connection.execute(
                "DELETE FROM outfit_result_cache WHERE rowid NOT IN "
                "(SELECT rowid FROM outfit_result_cache ORDER BY requested_at DESC, rowid DESC LIMIT ?)",
                (self._max_entries,),
            )
        cached = self._read(key)
        if cached is not None:
            return cached
        if self._weekly_batch_only and kind == "weekly":
            raise WeeklyOutfitNotReadyError()
        with self._lock_for(key):
            cached = self._read(key)
            if cached is not None:
                return cached
            return self._generate(key)

    def _read(self, key: CacheKey) -> OutfitResult | None:
        """한국 날짜가 같고 세 번의 갱신 주기 이내인 정상 결과만 사용"""
        with closing(connect_database(self._database_path)) as connection:
            row = connection.execute(
                "SELECT payload, updated_at FROM outfit_result_cache WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                key,
            ).fetchone()
        if row is None or row["payload"] is None:
            return None
        now = self._clock().astimezone(KST)
        is_weekly_batch = self._weekly_batch_only and key[1].rsplit(":", 1)[-1] == "weekly"
        max_age = self._weekly_max_age_seconds if is_weekly_batch else self._refresh_seconds * 3
        if not 0 <= now.timestamp() - row["updated_at"] <= max_age:
            return None
        try:
            result = RESULT_ADAPTERS[key[1].rsplit(":", 1)[-1]].validate_json(row["payload"])
        except ValidationError:
            return None
        if not is_weekly_batch and result.forecast.today != now.date():
            return None
        return result

    def _generate(self, key: CacheKey, record_attempt: bool = True) -> OutfitResult:
        """시도 시각을 기록하고 성공한 결과만 원자적으로 교체"""
        if record_attempt:
            with closing(connect_database(self._database_path)) as connection, connection:
                connection.execute(
                    "UPDATE outfit_result_cache SET attempted_at=?, prepared_for=0 "
                    "WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                    (self._clock().timestamp(), *key),
                )
        service = self._service_factory()
        kind, latitude, longitude = key[1].rsplit(":", 1)[-1], key[2], key[3]
        previous = self._read(key) if self._reuse_unchanged_weather else None
        result: OutfitResult
        if kind == "today":
            if previous is None:
                result = service.get_today(latitude, longitude)
            elif isinstance(previous, TodayOutfitResult):
                result = service.refresh_today(latitude, longitude, previous)
            else:
                raise OutfitForecastError()
        elif kind == "weekly":
            if previous is None:
                result = service.get_weekly(latitude, longitude)
            elif isinstance(previous, WeeklyOutfitResult):
                result = service.refresh_weekly(latitude, longitude, previous)
            else:
                raise OutfitForecastError()
        else:
            raise ValueError("지원하지 않는 추천 조회 종류입니다.")
        if result.forecast.today != self._clock().astimezone(KST).date():
            raise OutfitForecastError()
        payload = _dump_result(result)
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "UPDATE outfit_result_cache SET payload=?, updated_at=? "
                "WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                (payload, self._clock().timestamp(), *key),
            )
        return result

    def prepare_region(
        self, location_id: int, kind: str, latitude: float, longitude: float, lead_seconds: float,
    ) -> tuple[float, OutfitResult | None] | None:
        """공통 갱신 기한 전 새 날씨와 기본 버전을 준비하되 정규 갱신 주기는 유지"""
        if kind not in RESULT_ADAPTERS:
            raise ValueError("지원하지 않는 추천 조회 종류입니다.")
        if self._weekly_batch_only and kind == "weekly":
            return None
        key = self._key(f"region:{location_id}:{kind}", latitude, longitude)
        with self._lock_for(key):
            with closing(connect_database(self._database_path)) as connection:
                row = connection.execute(
                    "SELECT attempted_at, prepared_for FROM outfit_result_cache "
                    "WHERE scope=? AND kind=? AND latitude=? AND longitude=?", key,
                ).fetchone()
            if row is None:
                return None
            due = row["attempted_at"] + self._refresh_seconds
            now = self._clock().astimezone(KST)
            if now.timestamp() < due - lead_seconds or datetime.fromtimestamp(due, KST).date() != now.date():
                return None
            if row["prepared_for"] == -due:
                return None
            if row["prepared_for"] < due:
                with closing(connect_database(self._database_path)) as connection, connection:
                    connection.execute(
                        "UPDATE outfit_result_cache SET prepared_for=? "
                        "WHERE scope=? AND kind=? AND latitude=? AND longitude=?", (-due, *key),
                    )
                self._generate(key, record_attempt=False)
                with closing(connect_database(self._database_path)) as connection, connection:
                    connection.execute(
                        "UPDATE outfit_result_cache SET prepared_for=? "
                        "WHERE scope=? AND kind=? AND latitude=? AND longitude=?", (due, *key),
                    )
            return due, self._read(key)

    def refresh_due(self, stopped: Event | None = None) -> None:
        """조회 이력이 있는 지역을 순차 갱신하고 실패한 지역은 다음 주기에 재시도"""
        with closing(connect_database(self._database_path)) as connection:
            rows = connection.execute(
                "SELECT kind, latitude, longitude FROM outfit_result_cache "
                "WHERE scope=? AND requested_at>=? ORDER BY attempted_at",
                (self._scope, self._clock().timestamp() - 86400),
            ).fetchall()
        for row in rows:
            if stopped is not None and stopped.is_set():
                return
            if self._weekly_batch_only and row["kind"].rsplit(":", 1)[-1] == "weekly":
                continue
            key = self._key(row["kind"], row["latitude"], row["longitude"])
            with self._lock_for(key):
                if stopped is not None and stopped.is_set():
                    return
                with closing(connect_database(self._database_path)) as connection:
                    current = connection.execute(
                        "SELECT attempted_at, prepared_for FROM outfit_result_cache WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                        key,
                    ).fetchone()
                now = self._clock().astimezone(KST)
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                if current is None or (
                    now.timestamp() - current["attempted_at"] < self._refresh_seconds
                    and current["attempted_at"] >= midnight
                ):
                    continue
                due = current["attempted_at"] + self._refresh_seconds
                if current["prepared_for"] >= due and self._read(key) is not None:
                    with closing(connect_database(self._database_path)) as connection, connection:
                        connection.execute(
                            "UPDATE outfit_result_cache SET attempted_at=?, prepared_for=0 "
                            "WHERE scope=? AND kind=? AND latitude=? AND longitude=?", (due, *key),
                        )
                    continue
                try:
                    self._generate(key)
                except Exception as exc:
                    logger.warning("옷차림 사전 갱신 실패: kind=%s, cause=%s", row["kind"], type(exc).__name__)

    def run_weekly_batch(self, stopped: Event | None = None, on_ready=None, force: bool = False) -> dict:
        """한국 시간 지정된 한 시간 안에 하루 한 번 시작하고 요청 경로와 분리해 주간 생성"""
        now = self._clock().astimezone(KST)
        if not force and now.hour != self._weekly_batch_hour:
            return {"status": "not_due", "generated": 0, "failed": 0}
        run_date = now.date().isoformat()
        with closing(connect_database(self._database_path)) as connection, connection:
            claimed = connection.execute(
                "INSERT OR IGNORE INTO outfit_weekly_batch_runs (scope, run_date, started_at, status) VALUES (?, ?, ?, 'running')",
                (self._scope, run_date, now.timestamp()),
            ).rowcount
        if not claimed:
            return {"status": "already_run", "generated": 0, "failed": 0}
        started = perf_counter()
        logger.info("주간 추천 배치 시작: run_date=%s", run_date)
        generated, failed, personalized_generated = 0, 0, 0
        status = "completed"
        try:
            with closing(connect_database(self._database_path)) as connection:
                rows = connection.execute(
                    "SELECT kind, latitude, longitude, requested_at FROM outfit_result_cache "
                    "WHERE scope=? AND requested_at>=? ORDER BY requested_at DESC",
                    (self._scope, now.timestamp() - 86400),
                ).fetchall()
            targets = {}
            for row in rows:
                prefix = row["kind"].rsplit(":", 1)
                kind = prefix[0] + ":weekly" if len(prefix) == 2 else "weekly"
                key = self._key(kind, row["latitude"], row["longitude"])
                targets.setdefault(key, row["requested_at"])
            for key, requested_at in targets.items():
                if stopped is not None and stopped.is_set():
                    status = "stopped"
                    break
                try:
                    with self._lock_for(key):
                        with closing(connect_database(self._database_path)) as connection, connection:
                            connection.execute(
                                "INSERT INTO outfit_result_cache (scope, kind, latitude, longitude, requested_at) "
                                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(scope, kind, latitude, longitude) "
                                "DO UPDATE SET requested_at=MAX(requested_at, excluded.requested_at)", (*key, requested_at),
                            )
                            connection.execute(
                                "DELETE FROM outfit_result_cache WHERE rowid NOT IN "
                                "(SELECT rowid FROM outfit_result_cache ORDER BY requested_at DESC, rowid DESC LIMIT ?)",
                                (self._max_entries,),
                            )
                            present = connection.execute(
                                "SELECT 1 FROM outfit_result_cache WHERE scope=? AND kind=? AND latitude=? AND longitude=?", key,
                            ).fetchone()
                        if present is None:
                            continue
                        result = self._generate(key)
                    generated += 1
                    if on_ready is not None:
                        personal = on_ready(key, result, stopped)
                        if personal:
                            failed += personal["failed"]
                            personalized_generated += personal["generated"]
                except Exception as exc:
                    failed += 1
                    logger.warning("주간 배치 항목 실패: kind=%s, cause=%s", key[1], type(exc).__name__)
        except Exception:
            status = "failed"
            raise
        finally:
            if failed and status == "completed":
                status = "partial_failure"
            with closing(connect_database(self._database_path)) as connection, connection:
                connection.execute(
                    "UPDATE outfit_weekly_batch_runs SET status=?, finished_at=? WHERE scope=? AND run_date=?",
                    (status, self._clock().timestamp(), self._scope, run_date),
                )
            logger.info(
                "주간 추천 배치 종료: status=%s, common=%s, personal=%s, failed=%s, elapsed_seconds=%.2f",
                status, generated, personalized_generated, failed, perf_counter() - started,
            )
        return {
            "status": status, "generated": generated, "personalized_generated": personalized_generated,
            "failed": failed, "elapsed_seconds": perf_counter() - started,
        }


# 개인화 추천 캐시
class SQLitePersonalizedOutfitCache:
    def __init__(
        self, database_path: Path, scope: str, personalizer: OutfitPersonalizer,
        common: CachedOutfitService, locations: LocationReader, lead_seconds: float = 600,
        clock: Callable[[], datetime] | None = None, max_entries: int = 4096,
        weekly_batch_only: bool = False,
    ) -> None:
        """조건 조합을 저장하고 사용자 식별자 없이 같은 조건의 결과를 공유"""
        self._database_path = database_path
        self._scope = scope
        self._personalizer = personalizer
        self._common = common
        self._locations = locations
        self._lead_seconds = lead_seconds
        self._clock = clock or (lambda: datetime.now(KST))
        self._max_entries = max_entries
        self._weekly_batch_only = weekly_batch_only
        self._locks: WeakValueDictionary[str, LockType] = WeakValueDictionary()
        self._guard = Lock()
        with closing(connect_database(database_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outfit_personal_results "
                "(cache_key TEXT PRIMARY KEY, payload BLOB NOT NULL, created_at REAL NOT NULL)",
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outfit_personal_targets "
                "(profile_key TEXT PRIMARY KEY, scope TEXT NOT NULL, location_id INTEGER NOT NULL, "
                "kind TEXT NOT NULL, preferences BLOB NOT NULL, requested_at REAL NOT NULL, attempted_slot REAL NOT NULL DEFAULT 0)",
            )

    def _lock_for(self, key: str) -> LockType:
        """동일 생성 조합에만 잠금을 걸고 사용 종료 후 자동 회수"""
        with self._guard:
            generation_lock = self._locks.get(key)
            if generation_lock is None:
                generation_lock = Lock()
                self._locks[key] = generation_lock
            return generation_lock

    def _profile_key(self, location_id: int, kind: str, preferences: OutfitPreferences) -> str:
        """기본 버전과 별개로 다음 배치에 사용할 조건 조합 식별"""
        profile = json.dumps([self._scope, location_id, kind, asdict(preferences)], sort_keys=True)
        return hashlib.sha256(profile.encode()).hexdigest()

    def register(self, location_id: int, kind: str, preferences: OutfitPreferences) -> str:
        """기본 결과가 아직 없는 주간 개인 조건도 다음 야간 배치를 위해 등록"""
        if kind not in RESULT_ADAPTERS:
            raise ValueError("지원하지 않는 추천 조회 종류입니다.")
        profile_key = self._profile_key(location_id, kind, preferences)
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "INSERT INTO outfit_personal_targets (profile_key, scope, location_id, kind, preferences, requested_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(profile_key) DO UPDATE SET requested_at=excluded.requested_at",
                (profile_key, self._scope, location_id, kind, PREFERENCES_ADAPTER.dump_json(preferences), self._clock().timestamp()),
            )
            connection.execute(
                "DELETE FROM outfit_personal_targets WHERE profile_key NOT IN "
                "(SELECT profile_key FROM outfit_personal_targets ORDER BY requested_at DESC, profile_key LIMIT ?)",
                (self._max_entries,),
            )
        return profile_key

    def get(
        self, location_id: int, kind: str, base: TodayOutfitResult | WeeklyOutfitResult,
        preferences: OutfitPreferences, register: bool = True, from_weekly_batch: bool = False,
    ) -> tuple[PersonalizedOutfits, bool]:
        """주간은 준비된 개인 결과만 제공하고 오늘의 최초 조합은 동적 생성"""
        if kind == "today" and isinstance(base, TodayOutfitResult):
            recommendations = (base.recommendation,)
        elif kind == "weekly" and isinstance(base, WeeklyOutfitResult):
            recommendations = base.daily
        else:
            raise OutfitForecastError()
        if register:
            profile_key = self.register(location_id, kind, preferences)
        else:
            profile_key = self._profile_key(location_id, kind, preferences)
        base_version = base.base_version or hashlib.sha256(_dump_result(base)).hexdigest()
        cache_key = hashlib.sha256((profile_key + base_version).encode()).hexdigest()
        with self._lock_for(cache_key):
            with closing(connect_database(self._database_path)) as connection:
                row = connection.execute("SELECT payload FROM outfit_personal_results WHERE cache_key=?", (cache_key,)).fetchone()
            if row is not None:
                try:
                    cached = PERSONAL_ADAPTER.validate_json(row["payload"])
                    if cached.base_version == base_version:
                        return cached, True
                except ValidationError:
                    pass
            if self._weekly_batch_only and kind == "weekly" and not from_weekly_batch:
                raise WeeklyOutfitNotReadyError()
            generated = self._personalizer.personalize(GeneratedOutfits(recommendations, base.engine), preferences)
            if tuple(item.weather for item in generated.recommendations) != tuple(item.weather for item in recommendations):
                raise OutfitLlmResponseError()
            result = PersonalizedOutfits(generated, self._clock(), uuid4().hex, base_version)
            with closing(connect_database(self._database_path)) as connection, connection:
                connection.execute(
                    "INSERT INTO outfit_personal_results VALUES (?, ?, ?) "
                    "ON CONFLICT(cache_key) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at",
                    (cache_key, PERSONAL_ADAPTER.dump_json(result), self._clock().timestamp()),
                )
                connection.execute(
                    "DELETE FROM outfit_personal_results WHERE cache_key NOT IN "
                    "(SELECT cache_key FROM outfit_personal_results ORDER BY created_at DESC, cache_key LIMIT ?)",
                    (self._max_entries,),
                )
            return result, False

    def refresh_due(self, stopped=None) -> None:
        """최근 요청한 조건만 갱신 10분 전부터 준비하고 실패한 조합은 같은 주기 재호출 방지"""
        with closing(connect_database(self._database_path)) as connection:
            targets = connection.execute(
                "SELECT * FROM outfit_personal_targets WHERE scope=? AND requested_at>=? ORDER BY requested_at DESC",
                (self._scope, self._clock().timestamp() - 86400),
            ).fetchall()
        for target in targets:
            if stopped is not None and stopped.is_set():
                return
            if self._weekly_batch_only and target["kind"] == "weekly":
                continue
            try:
                location = self._locations.get(target["location_id"])
                prepared = self._common.prepare_region(
                    location.id, target["kind"], location.latitude, location.longitude, self._lead_seconds,
                )
                if prepared is None:
                    continue
                slot, base = prepared
                if base is None or target["attempted_slot"] >= slot:
                    continue
                with closing(connect_database(self._database_path)) as connection, connection:
                    connection.execute(
                        "UPDATE outfit_personal_targets SET attempted_slot=? WHERE profile_key=?", (slot, target["profile_key"]),
                    )
                self.get(
                    location.id, target["kind"], base,
                    PREFERENCES_ADAPTER.validate_json(target["preferences"]), register=False,
                )
            except Exception as exc:
                logger.warning("개인 맞춤 사전 생성 실패: kind=%s, cause=%s", target["kind"], type(exc).__name__)

    def prepare_weekly(self, key: tuple, base: WeeklyOutfitResult, stopped=None) -> dict:
        """주간 기본 결과가 준비된 지역부터 등록된 개인 조건을 같은 야간 작업에서 생성"""
        parts = key[1].split(":")
        if len(parts) != 3 or parts[0] != "region":
            return {"generated": 0, "failed": 0}
        region_id = int(parts[1])
        with closing(connect_database(self._database_path)) as connection:
            targets = connection.execute(
                "SELECT preferences FROM outfit_personal_targets "
                "WHERE scope=? AND location_id=? AND kind='weekly' AND requested_at>=? ORDER BY requested_at DESC",
                (self._scope, region_id, self._clock().timestamp() - 86400),
            ).fetchall()
        generated, failed = 0, 0
        for target in targets:
            if stopped is not None and stopped.is_set():
                break
            try:
                self.get(
                    region_id, "weekly", base, PREFERENCES_ADAPTER.validate_json(target["preferences"]),
                    register=False, from_weekly_batch=True,
                )
                generated += 1
            except Exception as exc:
                failed += 1
                logger.warning("주간 개인 맞춤 배치 실패: cause=%s", type(exc).__name__)
        return {"generated": generated, "failed": failed}
