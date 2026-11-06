"""개인 조건별 동적 생성 결과 저장과 공통 갱신 전 사전 생성."""

import hashlib
import json
import logging
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4
from weakref import WeakValueDictionary

from pydantic import TypeAdapter, ValidationError

from app.common.database import connect_database
from app.outfits.application.dto import GeneratedOutfits, PersonalizedOutfits, TodayOutfitResult, WeeklyOutfitResult
from app.outfits.application.exceptions import OutfitLlmResponseError, WeeklyOutfitNotReadyError
from app.outfits.application.ports import OutfitPersonalizer
from app.outfits.domain.preferences import OutfitPreferences
from app.outfits.infrastructure.result_cache import CachedOutfitService, RESULT_ADAPTERS
from app.weather.application.ports import LocationCatalog
from app.weather.domain.models import KST

logger = logging.getLogger(__name__)
PERSONAL_ADAPTER = TypeAdapter(PersonalizedOutfits)
PREFERENCES_ADAPTER = TypeAdapter(OutfitPreferences)


class SQLitePersonalizedOutfitCache:
    def __init__(
        self, database_path: Path, scope: str, personalizer: OutfitPersonalizer,
        common: CachedOutfitService, locations: LocationCatalog, lead_seconds: float = 600,
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
        self._locks = WeakValueDictionary()
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

    def _lock_for(self, key: str):
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
            raise ValueError("Unknown outfit kind")
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
        if register:
            profile_key = self.register(location_id, kind, preferences)
        else:
            profile_key = self._profile_key(location_id, kind, preferences)
        base_version = base.base_version or hashlib.sha256(RESULT_ADAPTERS[kind].dump_json(base)).hexdigest()
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
            recommendations = (base.recommendation,) if kind == "today" else base.daily
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
