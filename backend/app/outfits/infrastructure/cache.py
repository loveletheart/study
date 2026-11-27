"""공통·개인 추천과 생성 대상을 SQLite에 보관한다."""


# 표준 라이브러리
import logging
import hashlib
import json
from _thread import LockType
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection, OperationalError
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
from app.common.errors.codes import ErrorCode
from app.common.errors.exceptions import AppError
from app.outfits.application.dto import (
    TodayOutfitResult,
    WeeklyOutfitResult,
    OutfitForecast,
    GeneratedOutfits,
    PersonalizedOutfits,
)
from app.outfits.application.exceptions import (
    OutfitCloudRateLimitError,
    OutfitCloudTimeoutError,
    OutfitCloudUnavailableError,
    OutfitForecastError,
    OutfitLlmResponseError,
    OutfitLlmTimeoutError,
    OutfitLlmUnavailableError,
    WeeklyOutfitNotReadyError,
)
from app.outfits.application.services import OutfitService
from app.weather.domain.models import KST
from app.outfits.application.ports import OutfitPersonalizer
from app.outfits.domain.clothing_style import conflicting_clothes, is_one_piece_clothing
from app.outfits.domain.models import ClothingPreference, OutfitPreferences, OutfitType
from app.weather.application.ports import LocationReader
from app.weather.application.exceptions import (
    WeatherProviderTimeoutError,
    WeatherProviderUnavailableError,
    WeatherRateLimitError,
)
from app.outfits.infrastructure.weekly_batch import (
    CacheKey,
    WeeklyBatchLeaseLostError,
    WeeklyBatchRun,
    WeeklyBatchStore,
    WeeklyBatchTarget,
)


# 로그
logger = logging.getLogger(__name__)


# 캐시 키와 결과 타입
OutfitResult = TodayOutfitResult | WeeklyOutfitResult
WEEKLY_RETRYABLE_ERRORS = (
    OutfitLlmTimeoutError, OutfitLlmUnavailableError,
    OutfitCloudTimeoutError, OutfitCloudUnavailableError, OutfitCloudRateLimitError,
    WeatherProviderTimeoutError, WeatherProviderUnavailableError, WeatherRateLimitError,
    OperationalError,
)


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


def _valid_personal_clothing(generated: GeneratedOutfits, preference: ClothingPreference) -> bool:
    """개인 추천의 스타일과 원피스 항목을 저장 전과 재조회 시 검사한다."""
    return all(
        not conflicting_clothes(asdict(look), preference)
        and (look.outfit_type != OutfitType.ONE_PIECE or is_one_piece_clothing(look.one_piece))
        for day in generated.recommendations
        for look in (day.best, day.worst)
    )


# 공통 추천 캐시
class CachedOutfitService:
    def __init__(
        self, database_path: Path, scope: str, service_factory: Callable[[], OutfitService],
        refresh_seconds: float = 3600, clock: Callable[[], datetime] | None = None,
        reuse_unchanged_weather: bool = False,
        max_entries: int = 128,
        weekly_batch_only: bool = False, weekly_batch_hour: int = 1, weekly_max_age_seconds: float = 172800,
        weather_refresh_workers: int = 4,
        *, previous_scope: str | None = None,
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
        self._weather_refresh_workers = weather_refresh_workers
        self._clock = clock or (lambda: datetime.now(KST))
        self._generation_locks: WeakValueDictionary[CacheKey, LockType] = WeakValueDictionary()
        self._generation_locks_guard = Lock()
        self._refresh_lock = Lock()
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
        self._weekly_batch = WeeklyBatchStore(database_path, scope, self._clock, previous_scope=previous_scope)

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
            self._prune_cache(connection, key)
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

    def _prune_cache(self, connection: Connection, key: CacheKey) -> None:
        """현재 요청과 재개 가능한 당일 배치의 주간 행을 용량 정리에서 보호한다."""
        run_date = self._clock().astimezone(KST).date().isoformat()
        connection.execute(
            """
            WITH ranked_cache AS (
                SELECT cache.rowid AS entry_id, target.scope IS NOT NULL AS reserved,
                    ROW_NUMBER() OVER (
                        ORDER BY ((cache.scope, cache.kind, cache.latitude, cache.longitude) = (?, ?, ?, ?)) DESC,
                            (target.scope IS NOT NULL) DESC, cache.requested_at DESC, cache.rowid DESC
                    ) AS cache_rank
                FROM outfit_result_cache AS cache
                LEFT JOIN outfit_weekly_batch_runs AS run
                    ON run.scope=cache.scope AND run.run_date=? AND run.status IN ('running', 'stopped', 'retry_wait')
                LEFT JOIN outfit_weekly_batch_targets AS target
                    ON target.scope=run.scope AND target.run_date=run.run_date AND target.kind=cache.kind
                    AND target.latitude=cache.latitude AND target.longitude=cache.longitude
            )
            DELETE FROM outfit_result_cache
            WHERE rowid IN (SELECT entry_id FROM ranked_cache WHERE cache_rank>? AND NOT reserved)
            """,
            (*key, run_date, self._max_entries),
        )

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

    def _generate(
        self, key: CacheKey, record_attempt: bool = True,
        *, loaded: tuple[OutfitService, OutfitForecast] | None = None,
        on_saved: Callable[[Connection], None] | None = None,
    ) -> OutfitResult:
        """시도 시각을 기록하고 성공한 결과만 원자적으로 교체"""
        if record_attempt:
            with closing(connect_database(self._database_path)) as connection, connection:
                connection.execute(
                    "UPDATE outfit_result_cache SET attempted_at=?, prepared_for=0 "
                    "WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                    (self._clock().timestamp(), *key),
                )
        service, forecast = loaded if loaded is not None else (self._service_factory(), None)
        kind, latitude, longitude = key[1].rsplit(":", 1)[-1], key[2], key[3]
        previous = self._read(key) if self._reuse_unchanged_weather else None
        result: OutfitResult
        if kind == "today":
            if previous is not None and not isinstance(previous, TodayOutfitResult):
                raise OutfitForecastError()
            if forecast is not None:
                result = service.recommend_today(forecast, previous)
            elif previous is None:
                result = service.get_today(latitude, longitude)
            else:
                result = service.refresh_today(latitude, longitude, previous)
        elif kind == "weekly":
            if previous is not None and not isinstance(previous, WeeklyOutfitResult):
                raise OutfitForecastError()
            if forecast is not None:
                result = service.recommend_weekly(forecast, previous)
            elif previous is None:
                result = service.get_weekly(latitude, longitude)
            else:
                result = service.refresh_weekly(latitude, longitude, previous)
        else:
            raise ValueError("지원하지 않는 추천 조회 종류입니다.")
        if result.forecast.today != self._clock().astimezone(KST).date():
            raise OutfitForecastError()
        payload = _dump_result(result)
        with closing(connect_database(self._database_path)) as connection, connection:
            saved = connection.execute(
                "UPDATE outfit_result_cache SET payload=?, updated_at=? "
                "WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                (payload, self._clock().timestamp(), *key),
            ).rowcount
            if on_saved is not None:
                if not saved:
                    raise OutfitForecastError()
                on_saved(connection)
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
        """시군구 예보를 동시에 조회하고 먼저 끝난 결과부터 저장한다."""
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            self._refresh_requested(stopped)
        finally:
            self._refresh_lock.release()

    def _refresh_requested(self, stopped: Event | None) -> None:
        now = self._clock().astimezone(KST)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with closing(connect_database(self._database_path)) as connection:
            rows = connection.execute(
                "SELECT kind, latitude, longitude, (attempted_at<=? OR attempted_at<?) AS due "
                "FROM outfit_result_cache WHERE scope=? AND requested_at>=? "
                "ORDER BY requested_at DESC, rowid DESC",
                (now.timestamp() - self._refresh_seconds, midnight, self._scope, now.timestamp() - 86400),
            ).fetchall()
        regions: dict[str, list[CacheKey]] = {}
        representatives: dict[str, tuple[float, float]] = {}
        coordinates: list[CacheKey] = []
        for row in rows:
            kind = row["kind"]
            if self._weekly_batch_only and kind.rsplit(":", 1)[-1] == "weekly":
                continue
            location = row["latitude"], row["longitude"]
            key = self._key(kind, *location)
            if kind.startswith("region:"):
                region = kind.rsplit(":", 1)[0]
                if representatives.setdefault(region, location) == location and row["due"]:
                    regions.setdefault(region, []).append(key)
            elif row["due"]:
                coordinates.append(key)
        if regions:
            self._refresh_regions(regions, stopped)
        for key in coordinates:
            if stopped is not None and stopped.is_set():
                return
            with self._lock_for(key):
                if stopped is not None and stopped.is_set():
                    return
                if self._claim_refresh([key]):
                    self._save_refresh(key)

    def _claim_refresh(self, keys: list[CacheKey]) -> list[CacheKey]:
        """외부 호출 전에 갱신 기한을 재확인하고 시도 시각을 저장한다."""
        claimed = []
        now = self._clock().astimezone(KST)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            for key in keys:
                current = connection.execute(
                    "SELECT attempted_at, prepared_for FROM outfit_result_cache "
                    "WHERE scope=? AND kind=? AND latitude=? AND longitude=?", key,
                ).fetchone()
                if current is None or (
                    now.timestamp() - current["attempted_at"] < self._refresh_seconds
                    and current["attempted_at"] >= midnight
                ):
                    continue
                due = current["attempted_at"] + self._refresh_seconds
                prepared = current["prepared_for"] >= due and self._read(key) is not None
                connection.execute(
                    "UPDATE outfit_result_cache SET attempted_at=?, prepared_for=0 "
                    "WHERE scope=? AND kind=? AND latitude=? AND longitude=?",
                    (due if prepared else now.timestamp(), *key),
                )
                if not prepared:
                    claimed.append(key)
        return claimed

    def _refresh_regions(self, regions: dict[str, list[CacheKey]], stopped: Event | None) -> None:
        # 키 잠금은 예보 조회부터 추천 저장까지 유지하되, 모델은 완료 결과를 처리하는 스레드에서 호출한다.
        with ExitStack() as pending, ThreadPoolExecutor(max_workers=self._weather_refresh_workers) as pool:
            futures = {}
            for region, keys in regions.items():
                if stopped is not None and stopped.is_set():
                    break
                locks = pending.enter_context(ExitStack())
                future = pool.submit(self._load_refresh_forecast, keys, locks, stopped)
                futures[future] = region, locks
            for future in as_completed(futures):
                region, locks = futures[future]
                with locks:
                    try:
                        loaded = future.result()
                    except Exception as exc:
                        logger.warning("시군구 날씨 갱신 실패: region=%s, cause=%s", region, type(exc).__name__)
                        continue
                    if loaded is not None and (stopped is None or not stopped.is_set()):
                        keys, service, forecast = loaded
                        for key in keys:
                            if stopped is not None and stopped.is_set():
                                return
                            self._save_refresh(key, (service, forecast))

    def _load_refresh_forecast(
        self, keys: list[CacheKey], locks: ExitStack, stopped: Event | None,
    ) -> tuple[list[CacheKey], OutfitService, OutfitForecast] | None:
        if stopped is not None and stopped.is_set():
            return None
        targets = []
        for key in keys:
            lock = self._lock_for(key)
            if lock.acquire(blocking=False):
                locks.callback(lock.release)
                targets.append(key)
        if not targets:
            return None
        claimed = self._claim_refresh(targets)
        if not claimed:
            return None
        service = self._service_factory()
        return claimed, service, service.get_forecast(*claimed[0][2:])

    def _save_refresh(self, key: CacheKey, loaded: tuple[OutfitService, OutfitForecast] | None = None) -> None:
        try:
            self._generate(key, record_attempt=False, loaded=loaded)
        except Exception as exc:
            logger.warning("옷차림 사전 갱신 실패: kind=%s, cause=%s", key[1], type(exc).__name__)

    def run_weekly_batch(
        self, stopped: Event | None = None, on_ready=None, force: bool = False, *, retry_failed: bool = False,
    ) -> dict:
        """예약 시간이 지난 뒤 당일 배치의 미완료 대상을 처리한다."""
        now = self._clock().astimezone(KST)
        if not force and now.hour < self._weekly_batch_hour:
            return {"status": "not_due", "generated": 0, "failed": 0}

        status, run, targets = self._weekly_batch.claim(now, retry_failed=retry_failed)
        if run is None:
            return {"status": status, "generated": 0, "failed": 0}

        def check_lease(connection: Connection) -> None:
            self._weekly_batch.check_lease(connection, run)

        started = perf_counter()
        logger.info("주간 추천 배치 시작: run_date=%s, targets=%s", run.date, len(targets))
        generated, failed, personalized_generated = 0, 0, 0
        interrupted = False
        try:
            with self._weekly_batch.maintain_lease(run) as lease_lost:
                for target in targets:
                    if lease_lost.is_set():
                        raise WeeklyBatchLeaseLostError()
                    if (
                        (stopped is not None and stopped.is_set())
                        or self._clock().astimezone(KST).date().isoformat() != run.date
                    ):
                        interrupted = True
                        break
                    try:
                        with self._lock_for(target.key):
                            result, created = self._prepare_weekly_common(run, target)
                        generated += int(created)
                        if lease_lost.is_set():
                            raise WeeklyBatchLeaseLostError()
                        personal = (
                            on_ready(target.key, result, stopped, check_lease=check_lease)
                            if on_ready is not None else None
                        )
                    except WeeklyBatchLeaseLostError:
                        raise
                    except Exception as exc:
                        failed += 1
                        error_code = exc.error_code if isinstance(exc, AppError) else ErrorCode.COMMON_INTERNAL_ERROR
                        self._record_weekly_failure(run, target, error_code, isinstance(exc, WEEKLY_RETRYABLE_ERRORS))
                        continue

                    if personal:
                        failed += personal["failed"]
                        personalized_generated += personal["generated"]
                    if stopped is not None and stopped.is_set():
                        interrupted = True
                        break
                    if personal and personal["failed"]:
                        self._record_weekly_failure(
                            run, target, personal.get("last_error_code") or ErrorCode.COMMON_INTERNAL_ERROR,
                            bool(personal.get("retryable_failed", personal["failed"])),
                        )
                    else:
                        self._weekly_batch.record(run, target, failed=False)
            status = self._weekly_batch.finish(run, stopped=interrupted)
        except WeeklyBatchLeaseLostError:
            status = "lease_lost"

        elapsed = perf_counter() - started
        logger.info(
            "주간 추천 배치 종료: status=%s, common=%s, personal=%s, failed=%s, elapsed_seconds=%.2f",
            status, generated, personalized_generated, failed, elapsed,
        )
        return {
            "status": status, "generated": generated, "personalized_generated": personalized_generated,
            "failed": failed, "elapsed_seconds": elapsed,
        }

    def _record_weekly_failure(
        self, run: WeeklyBatchRun, target: WeeklyBatchTarget, error_code: ErrorCode, retryable: bool,
    ) -> None:
        retry_at = self._weekly_batch.record(run, target, failed=True, retryable=retryable, error_code=error_code.value)
        logger.warning(
            "주간 배치 항목 실패: run_date=%s, kind=%s, error_code=%s, attempts=%s, next_retry_at=%s",
            run.date, target.key[1], error_code.value, target.failures + 1,
            datetime.fromtimestamp(retry_at, KST).isoformat() if retry_at else None,
        )

    def _prepare_weekly_common(
        self, run: WeeklyBatchRun, target: WeeklyBatchTarget,
    ) -> tuple[WeeklyOutfitResult, bool]:
        key = target.key
        if target.common_ready:
            existing = self._read(key)
            if isinstance(existing, WeeklyOutfitResult) and existing.forecast.today.isoformat() == run.date:
                return existing, False

        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self._weekly_batch.check_lease(connection, run)
            connection.execute(
                "INSERT INTO outfit_result_cache (scope, kind, latitude, longitude, requested_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(scope, kind, latitude, longitude) "
                "DO UPDATE SET requested_at=MAX(requested_at, excluded.requested_at)", (*key, target.requested_at),
            )
            self._prune_cache(connection, key)
            present = connection.execute(
                "SELECT 1 FROM outfit_result_cache WHERE scope=? AND kind=? AND latitude=? AND longitude=?", key,
            ).fetchone()
        if present is None:
            raise OutfitForecastError()

        def mark_ready(connection: Connection) -> None:
            if self._clock().astimezone(KST).date().isoformat() != run.date:
                raise OutfitForecastError()
            self._weekly_batch.mark_common_ready(connection, run, key)

        result = self._generate(key, on_saved=mark_ready)
        if not isinstance(result, WeeklyOutfitResult):
            raise OutfitForecastError()
        return result, True


# 개인화 추천 캐시
class SQLitePersonalizedOutfitCache:
    def __init__(
        self, database_path: Path, scope: str, personalizer: OutfitPersonalizer,
        common: CachedOutfitService, locations: LocationReader, lead_seconds: float = 600,
        clock: Callable[[], datetime] | None = None, max_entries: int = 4096,
        weekly_batch_only: bool = False,
        *, previous_scope: str | None = None,
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
        self._previous_scope = previous_scope
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
        *, check_lease: Callable[[Connection], None] | None = None,
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
                    if cached.base_version == base_version and _valid_personal_clothing(
                        cached.generated, preferences.clothing_preference,
                    ):
                        return cached, True
                except ValidationError:
                    pass
            if self._weekly_batch_only and kind == "weekly" and not from_weekly_batch:
                raise WeeklyOutfitNotReadyError()
            if check_lease is not None:
                with closing(connect_database(self._database_path)) as connection:
                    check_lease(connection)
            generated = self._personalizer.personalize(GeneratedOutfits(recommendations, base.engine), preferences)
            if tuple(item.weather for item in generated.recommendations) != tuple(item.weather for item in recommendations):
                raise OutfitLlmResponseError()
            if not _valid_personal_clothing(generated, preferences.clothing_preference):
                raise OutfitLlmResponseError()
            result = PersonalizedOutfits(generated, self._clock(), uuid4().hex, base_version)
            with closing(connect_database(self._database_path)) as connection, connection:
                if check_lease is not None:
                    connection.execute("BEGIN IMMEDIATE")
                    check_lease(connection)
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

    def prepare_weekly(
        self, key: CacheKey, base: WeeklyOutfitResult, stopped=None,
        *, check_lease: Callable[[Connection], None] | None = None,
    ) -> dict:
        """주간 기본 결과가 준비된 지역부터 등록된 개인 조건을 같은 야간 작업에서 생성"""
        parts = key[1].split(":")
        if len(parts) != 3 or parts[0] != "region":
            return {"generated": 0, "failed": 0}
        region_id = int(parts[1])
        with closing(connect_database(self._database_path)) as connection:
            targets = connection.execute(
                "SELECT preferences FROM outfit_personal_targets "
                "WHERE scope IN (?, ?) AND location_id=? AND kind='weekly' AND requested_at>=? "
                "GROUP BY preferences ORDER BY MAX(requested_at) DESC",
                (self._scope, self._previous_scope, region_id, self._clock().timestamp() - 86400),
            ).fetchall()
        generated, failed, retryable_failed = 0, 0, 0
        last_error_code = None
        for target in targets:
            if stopped is not None and stopped.is_set():
                break
            try:
                _, cached = self.get(
                    region_id, "weekly", base, PREFERENCES_ADAPTER.validate_json(target["preferences"]),
                    register=False, from_weekly_batch=True, check_lease=check_lease,
                )
                generated += int(not cached)
            except WeeklyBatchLeaseLostError:
                raise
            except Exception as exc:
                failed += 1
                retryable_failed += int(isinstance(exc, WEEKLY_RETRYABLE_ERRORS))
                last_error_code = exc.error_code if isinstance(exc, AppError) else ErrorCode.COMMON_INTERNAL_ERROR
                logger.warning("주간 개인 맞춤 배치 실패: region=%s, error_code=%s", region_id, last_error_code.value)
        return {
            "generated": generated, "failed": failed, "retryable_failed": retryable_failed, "last_error_code": last_error_code,
        }
