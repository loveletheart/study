"""관리자 대시보드에 필요한 운영 집계를 조회한다."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.common.database import connect_database
from app.users.application.dto import (
    AdminOverview,
    FeedbackOverview,
    WeeklyBatchHistoryEntry,
    WeeklyBatchOverview,
)


WEEKLY_BATCH_HISTORY_LIMIT = 7


def read_admin_overview(database_path: Path) -> AdminOverview:
    """같은 조회 시점의 가입 계정, 피드백 상태, 최근 배치 이력을 반환한다."""
    with closing(connect_database(database_path)) as connection, connection:
        connection.execute("BEGIN")
        accounts = connection.execute("SELECT COUNT(*) FROM user_credentials").fetchone()[0]
        existing_tables = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' "
            "AND name IN ('outfit_feedback', 'outfit_weekly_batch_runs', 'outfit_weekly_batch_targets')",
        )
        tables = {row["name"] for row in existing_tables}
        feedback = {}
        if "outfit_feedback" in tables:
            rows = connection.execute("SELECT status, COUNT(*) AS total FROM outfit_feedback GROUP BY status")
            feedback = {row["status"]: row["total"] for row in rows}

        history = []
        if "outfit_weekly_batch_runs" in tables:
            runs = connection.execute(
                "SELECT scope, run_date, status, started_at, finished_at FROM outfit_weekly_batch_runs "
                "ORDER BY run_date DESC, started_at DESC, scope LIMIT ?",
                (WEEKLY_BATCH_HISTORY_LIMIT,),
            )
            for run in runs:
                counts = {}
                if "outfit_weekly_batch_targets" in tables:
                    rows = connection.execute(
                        "SELECT status, COUNT(*) AS total FROM outfit_weekly_batch_targets "
                        "WHERE scope=? AND run_date=? GROUP BY status",
                        (run["scope"], run["run_date"]),
                    )
                    counts = {row["status"]: row["total"] for row in rows}
                finished_at = run["finished_at"]
                history.append(WeeklyBatchHistoryEntry(
                    batch=WeeklyBatchOverview(
                        run_date=run["run_date"],
                        status=run["status"],
                        pending=counts.get("pending", 0),
                        completed=counts.get("completed", 0),
                        failed=counts.get("failed", 0),
                    ),
                    started_at=datetime.fromtimestamp(run["started_at"], tz=timezone.utc),
                    finished_at=datetime.fromtimestamp(finished_at, tz=timezone.utc) if finished_at is not None else None,
                ))
    return AdminOverview(
        registered_accounts=accounts,
        feedback=FeedbackOverview(
            reported=feedback.get("reported", 0),
            draft=feedback.get("draft", 0),
            approved=feedback.get("approved", 0),
            rejected=feedback.get("rejected", 0),
        ),
        weekly_batch=history[0].batch if history else None,
        weekly_batch_history=tuple(history),
    )
