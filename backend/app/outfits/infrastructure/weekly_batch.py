"""SQLite에 주간 배치 실행권과 지역별 진행 상태를 저장한다."""

import logging
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from sqlite3 import Connection, Error as SQLiteError
from threading import Event, Thread
from typing import Callable
from uuid import uuid4

from app.common.database import connect_database


logger = logging.getLogger(__name__)
LEASE_SECONDS = 300
HEARTBEAT_SECONDS = 30
RETRY_DELAYS = (300, 900)
CacheKey = tuple[str, str, float, float]


@dataclass(frozen=True)
class WeeklyBatchRun:
    date: str
    token: str


@dataclass(frozen=True)
class WeeklyBatchTarget:
    key: CacheKey
    requested_at: float
    common_ready: bool
    failures: int


class WeeklyBatchLeaseLostError(RuntimeError):
    """만료된 실행권으로 진행 상태를 덮어쓰는 것을 막는다."""


class WeeklyBatchStore:
    def __init__(
        self, database_path: Path, scope: str, clock: Callable[[], datetime],
        *, previous_scope: str | None = None,
    ) -> None:
        self._database_path = database_path
        self._scope = scope
        self._previous_scope = previous_scope
        self._clock = clock
        with closing(connect_database(database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outfit_weekly_batch_runs "
                "(scope TEXT NOT NULL, run_date TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, "
                "status TEXT NOT NULL, lease_token TEXT, lease_expires_at REAL NOT NULL DEFAULT 0, "
                "PRIMARY KEY(scope, run_date))",
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(outfit_weekly_batch_runs)")}
            if "lease_token" not in columns:
                connection.execute("ALTER TABLE outfit_weekly_batch_runs ADD COLUMN lease_token TEXT")
            if "lease_expires_at" not in columns:
                connection.execute("ALTER TABLE outfit_weekly_batch_runs ADD COLUMN lease_expires_at REAL NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outfit_weekly_batch_targets "
                "(scope TEXT NOT NULL, run_date TEXT NOT NULL, kind TEXT NOT NULL, "
                "latitude REAL NOT NULL, longitude REAL NOT NULL, requested_at REAL NOT NULL, "
                "common_ready INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, "
                "status TEXT NOT NULL DEFAULT 'pending', retry_at REAL NOT NULL DEFAULT 0, last_error_code TEXT, "
                "personal_preferences TEXT, "
                "PRIMARY KEY(scope, run_date, kind, latitude, longitude), "
                "FOREIGN KEY(scope, run_date) REFERENCES outfit_weekly_batch_runs(scope, run_date) ON DELETE CASCADE)",
            )

            target_columns = {row["name"] for row in connection.execute("PRAGMA table_info(outfit_weekly_batch_targets)")}
            if "last_error_code" not in target_columns:
                connection.execute("ALTER TABLE outfit_weekly_batch_targets ADD COLUMN last_error_code TEXT")
            if "personal_preferences" not in target_columns:
                connection.execute("ALTER TABLE outfit_weekly_batch_targets ADD COLUMN personal_preferences TEXT")

    def claim(
        self, now: datetime, *, retry_failed: bool = False,
        snapshot_personal: Callable[[Connection, CacheKey, float], str] | None = None,
    ) -> tuple[str, WeeklyBatchRun | None, list[WeeklyBatchTarget]]:
        run_date, timestamp = now.date().isoformat(), now.timestamp()
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT started_at, status, lease_token, lease_expires_at "
                "FROM outfit_weekly_batch_runs WHERE scope=? AND run_date=?",
                (self._scope, run_date),
            ).fetchone()
            if previous is not None and (
                previous["status"] == "completed"
                or (not retry_failed and previous["status"] == "partial_failure" and previous["lease_token"] is not None)
                or (previous["status"] == "running" and previous["lease_expires_at"] > timestamp)
            ):
                return "already_run", None, []

            if retry_failed:
                if previous is None or previous["status"] != "partial_failure" or previous["lease_token"] is None:
                    return "no_failed_targets", None, []
                reopened = connection.execute(
                    "UPDATE outfit_weekly_batch_targets SET status='pending', retry_at=0 "
                    "WHERE scope=? AND run_date=? AND status='failed'",
                    (self._scope, run_date),
                ).rowcount
                if not reopened:
                    return "no_failed_targets", None, []

            run = WeeklyBatchRun(run_date, uuid4().hex)
            if previous is None or previous["lease_token"] is None:
                legacy_started_at = previous["started_at"] if previous is not None else None
                targets = self._snapshot(connection, timestamp, legacy_started_at)
                if not targets:
                    return "no_targets", None, []
                connection.execute(
                    "INSERT OR IGNORE INTO outfit_weekly_batch_runs (scope, run_date, started_at, status) "
                    "VALUES (?, ?, ?, 'running')",
                    (self._scope, run.date, timestamp),
                )
                started_at = legacy_started_at if legacy_started_at is not None else timestamp
                connection.executemany(
                    "INSERT INTO outfit_weekly_batch_targets "
                    "(scope, run_date, kind, latitude, longitude, requested_at, common_ready, personal_preferences) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            self._scope, run.date, *target.key[1:], target.requested_at, target.common_ready,
                            snapshot_personal(connection, target.key, started_at) if snapshot_personal is not None else None,
                        )
                        for target in targets
                    ],
                )
            else:
                rows = connection.execute(
                    "SELECT kind, latitude, longitude, requested_at, common_ready, failures, retry_at "
                    "FROM outfit_weekly_batch_targets WHERE scope=? AND run_date=? AND status='pending' "
                    "ORDER BY requested_at DESC, kind, latitude, longitude",
                    (self._scope, run.date),
                ).fetchall()
                targets = [
                    WeeklyBatchTarget(
                        (self._scope, row["kind"], row["latitude"], row["longitude"]),
                        row["requested_at"], bool(row["common_ready"]), row["failures"],
                    )
                    for row in rows if row["retry_at"] <= timestamp
                ]
                if rows and not targets:
                    return "retry_wait", None, []

            connection.execute(
                "UPDATE outfit_weekly_batch_runs SET status='running', finished_at=NULL, lease_token=?, lease_expires_at=? "
                "WHERE scope=? AND run_date=?",
                (run.token, timestamp + LEASE_SECONDS, self._scope, run.date),
            )
        return "running", run, targets

    def _snapshot(
        self, connection: Connection, timestamp: float, legacy_started_at: float | None,
    ) -> list[WeeklyBatchTarget]:
        rows = connection.execute(
            "SELECT scope, kind, latitude, longitude, requested_at, updated_at FROM outfit_result_cache "
            "WHERE scope IN (?, ?) AND requested_at>=? ORDER BY requested_at DESC, kind, latitude, longitude",
            (self._scope, self._previous_scope, timestamp - 86400),
        ).fetchall()
        targets: dict[CacheKey, float] = {}
        ready: set[CacheKey] = set()
        for row in rows:
            prefix, separator, kind = row["kind"].rpartition(":")
            weekly_kind = f"{prefix}:weekly" if separator else "weekly"
            key = (self._scope, weekly_kind, row["latitude"], row["longitude"])
            targets.setdefault(key, row["requested_at"])
            if (
                row["scope"] == self._scope and kind == "weekly" and legacy_started_at is not None
                and row["updated_at"] is not None and row["updated_at"] >= legacy_started_at
            ):
                ready.add(key)
        return [WeeklyBatchTarget(key, requested_at, key in ready, 0) for key, requested_at in targets.items()]

    def check_lease(self, connection: Connection, run: WeeklyBatchRun) -> None:
        """현재 실행권이 유효한 동안만 상태나 결과 저장을 허용한다."""
        owned = connection.execute(
            "SELECT 1 FROM outfit_weekly_batch_runs WHERE scope=? AND run_date=? "
            "AND status='running' AND lease_token=? AND lease_expires_at>?",
            (self._scope, run.date, run.token, self._clock().timestamp()),
        ).fetchone()
        if owned is None:
            raise WeeklyBatchLeaseLostError()

    @contextmanager
    def maintain_lease(self, run: WeeklyBatchRun):
        stopped, lost = Event(), Event()

        def renew() -> None:
            while not stopped.wait(HEARTBEAT_SECONDS):
                try:
                    with closing(connect_database(self._database_path)) as connection, connection:
                        timestamp = self._clock().timestamp()
                        updated = connection.execute(
                            "UPDATE outfit_weekly_batch_runs SET lease_expires_at=? WHERE scope=? AND run_date=? "
                            "AND status='running' AND lease_token=? AND lease_expires_at>?",
                            (timestamp + LEASE_SECONDS, self._scope, run.date, run.token, timestamp),
                        ).rowcount
                    if not updated:
                        lost.set()
                        return
                except SQLiteError as exc:
                    logger.warning("주간 배치 실행권 갱신 실패: cause=%s", type(exc).__name__)

        thread = Thread(target=renew, name="weekly-batch-lease", daemon=True)
        thread.start()
        try:
            yield lost
        finally:
            stopped.set()
            thread.join()

    def mark_common_ready(self, connection: Connection, run: WeeklyBatchRun, key: CacheKey) -> None:
        self.check_lease(connection, run)
        connection.execute(
            "UPDATE outfit_weekly_batch_targets SET common_ready=1 "
            "WHERE scope=? AND run_date=? AND kind=? AND latitude=? AND longitude=?",
            (self._scope, run.date, *key[1:]),
        )

    def record(
        self, run: WeeklyBatchRun, target: WeeklyBatchTarget, *,
        failed: bool, retryable: bool = False, error_code: str | None = None,
    ) -> float:
        failures = target.failures + int(failed)
        status, retry_at = "completed", 0.0
        if failed:
            status = "failed"
            if retryable and failures <= len(RETRY_DELAYS):
                status = "pending"
                retry_at = self._clock().timestamp() + RETRY_DELAYS[failures - 1]
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self.check_lease(connection, run)
            connection.execute(
                "UPDATE outfit_weekly_batch_targets SET status=?, failures=?, retry_at=?, "
                "last_error_code=COALESCE(?, last_error_code) "
                "WHERE scope=? AND run_date=? AND kind=? AND latitude=? AND longitude=?",
                (status, failures, retry_at, error_code, self._scope, run.date, *target.key[1:]),
            )
        return retry_at

    def finish(self, run: WeeklyBatchRun, *, stopped: bool) -> str:
        with closing(connect_database(self._database_path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            self.check_lease(connection, run)
            states = {
                row["status"] for row in connection.execute(
                    "SELECT DISTINCT status FROM outfit_weekly_batch_targets WHERE scope=? AND run_date=?",
                    (self._scope, run.date),
                )
            }
            if stopped and "pending" in states:
                status = "stopped"
            elif "pending" in states:
                status = "retry_wait"
            elif "failed" in states:
                status = "partial_failure"
            else:
                status = "completed"
            connection.execute(
                "UPDATE outfit_weekly_batch_runs SET status=?, finished_at=?, lease_expires_at=0 "
                "WHERE scope=? AND run_date=?",
                (status, self._clock().timestamp(), self._scope, run.date),
            )
        return status
