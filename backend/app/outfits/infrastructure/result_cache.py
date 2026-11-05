"""추천 결과를 SQLite에 보관하고 조회한 지역을 주기적으로 갱신한다."""

import logging
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from weakref import WeakValueDictionary

from pydantic import TypeAdapter, ValidationError

from app.common.database import connect_database
from app.outfits.application.dto import TodayOutfitResult, WeeklyOutfitResult
from app.outfits.application.exceptions import OutfitForecastError
from app.outfits.application.services import OutfitService
from app.weather.domain.models import KST

logger = logging.getLogger(__name__)
RESULT_ADAPTERS = {"today": TypeAdapter(TodayOutfitResult), "weekly": TypeAdapter(WeeklyOutfitResult)}
CREATE_CACHE_TABLE = """
CREATE TABLE IF NOT EXISTS outfit_result_cache (
    scope TEXT NOT NULL,
    kind TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    requested_at REAL NOT NULL,
    attempted_at REAL NOT NULL DEFAULT 0,
    updated_at REAL,
    payload BLOB,
    PRIMARY KEY (scope, kind, latitude, longitude)
)
"""


class CachedOutfitService:
    def __init__(
        self, database_path: Path, scope: str, service_factory: Callable[[], OutfitService],
        refresh_seconds: float = 3600, clock: Callable[[], datetime] | None = None,
    ) -> None:
        """저장 경로와 갱신 주기를 설정한다."""
        self._database_path = database_path
        self._scope = scope
        self._service_factory = service_factory
        self._refresh_seconds = refresh_seconds
        self._clock = clock or (lambda: datetime.now(KST))
        self._generation_locks = WeakValueDictionary()
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

    def get_today(self, latitude: float, longitude: float) -> TodayOutfitResult:
        """오늘 추천을 재사용하고 저장된 결과가 없을 때만 생성한다."""
        return self._get("today", latitude, longitude)

    def get_weekly(self, latitude: float, longitude: float) -> WeeklyOutfitResult:
        """주간 추천을 재사용하고 저장된 결과가 없을 때만 생성한다."""
        return self._get("weekly", latitude, longitude)

    def _key(self, kind: str, latitude: float, longitude: float) -> tuple:
        """제공사 설정·조회 종류·정확한 좌표로 저장 키 구성"""
        return self._scope, kind, latitude, longitude

    def _lock_for(self, key: tuple):
        """동일 키의 생성 잠금을 공유하고 사용자·대기자가 없으면 자동 회수"""
        with self._generation_locks_guard:
            generation_lock = self._generation_locks.get(key)
            if generation_lock is None:
                generation_lock = Lock()
                self._generation_locks[key] = generation_lock
            return generation_lock

    def _get(self, kind: str, latitude: float, longitude: float):
        """동시 최초 요청은 한 번만 생성하고 갱신 중에는 기존 결과 제공"""
        key = self._key(kind, latitude, longitude)
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "INSERT INTO outfit_result_cache (scope, kind, latitude, longitude, requested_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (scope, kind, latitude, longitude) DO UPDATE SET requested_at=excluded.requested_at",
                (*key, self._clock().timestamp()),
            )
            connection.execute(
                "DELETE FROM outfit_result_cache WHERE rowid NOT IN "
                "(SELECT rowid FROM outfit_result_cache ORDER BY requested_at DESC, rowid DESC LIMIT 128)",
            )
        cached = self._read(key)
        if cached is not None:
            return cached
        with self._lock_for(key):
            cached = self._read(key)
            if cached is not None:
                return cached
            return self._generate(key)

    def _read(self, key: tuple):
        """한국 날짜가 같고 세 번의 갱신 주기 이내인 정상 결과만 사용"""
        with closing(connect_database(self._database_path)) as connection:
            row = connection.execute(
                "SELECT payload, updated_at FROM outfit_result_cache WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                key,
            ).fetchone()
        if row is None or row["payload"] is None:
            return None
        now = self._clock().astimezone(KST)
        if not 0 <= now.timestamp() - row["updated_at"] <= self._refresh_seconds * 3:
            return None
        try:
            result = RESULT_ADAPTERS[key[1]].validate_json(row["payload"])
        except ValidationError:
            return None
        if result.forecast.today != now.date():
            return None
        return result

    def _generate(self, key: tuple):
        """시도 시각을 기록하고 성공한 결과만 원자적으로 교체"""
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "UPDATE outfit_result_cache SET attempted_at=? WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                (self._clock().timestamp(), *key),
            )
        service = self._service_factory()
        kind, latitude, longitude = key[1:]
        result = getattr(service, "get_" + kind)(latitude, longitude)
        if result.forecast.today != self._clock().astimezone(KST).date():
            raise OutfitForecastError()
        payload = RESULT_ADAPTERS[kind].dump_json(result)
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute(
                "UPDATE outfit_result_cache SET payload=?, updated_at=? "
                "WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                (payload, self._clock().timestamp(), *key),
            )
        return result

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
            key = self._key(row["kind"], row["latitude"], row["longitude"])
            with self._lock_for(key):
                if stopped is not None and stopped.is_set():
                    return
                with closing(connect_database(self._database_path)) as connection:
                    current = connection.execute(
                        "SELECT attempted_at FROM outfit_result_cache WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                        key,
                    ).fetchone()
                now = self._clock().astimezone(KST)
                midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                if current is None or (
                    now.timestamp() - current["attempted_at"] < self._refresh_seconds
                    and current["attempted_at"] >= midnight
                ):
                    continue
                try:
                    self._generate(key)
                except Exception as exc:
                    logger.warning("옷차림 사전 갱신 실패: kind=%s, cause=%s", row["kind"], type(exc).__name__)


class OutfitRefreshWorker:
    def __init__(self, service: CachedOutfitService) -> None:
        """서버 수명 동안 실행할 단일 갱신 작업 준비"""
        self._service = service
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="outfit-refresh", daemon=True)

    def start(self) -> None:
        """서버 시작을 막지 않고 저장된 지역의 갱신 시작"""
        self._thread.start()

    def stop(self) -> None:
        """추가 갱신을 중단하고 진행 중인 외부 요청은 기존 제한 시간 적용"""
        self._stopped.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        """분마다 갱신 기한을 확인하고 긴 생성 작업은 겹치지 않게 실행"""
        while not self._stopped.is_set():
            try:
                self._service.refresh_due(self._stopped)
            except Exception as exc:
                logger.warning("옷차림 갱신 작업 실패: cause=%s", type(exc).__name__)
            self._stopped.wait(60)
