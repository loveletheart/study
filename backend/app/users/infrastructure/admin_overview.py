"""관리자 대시보드에 필요한 운영 집계를 조회한다."""

from contextlib import closing
from pathlib import Path

from app.common.database import connect_database
from app.users.application.dto import AdminOverview, FeedbackOverview, WeeklyBatchOverview


def read_admin_overview(database_path: Path) -> AdminOverview:
    """같은 조회 시점의 가입 계정, 피드백 상태, 최근 배치 상태를 반환한다."""
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

        batch = None
        if "outfit_weekly_batch_runs" in tables:
            latest = connection.execute(
                "SELECT scope, run_date, status FROM outfit_weekly_batch_runs "
                "ORDER BY run_date DESC, started_at DESC, scope LIMIT 1",
            ).fetchone()
            if latest is not None:
                counts = {}
                if "outfit_weekly_batch_targets" in tables:
                    rows = connection.execute(
                        "SELECT status, COUNT(*) AS total FROM outfit_weekly_batch_targets "
                        "WHERE scope=? AND run_date=? GROUP BY status",
                        (latest["scope"], latest["run_date"]),
                    )
                    counts = {row["status"]: row["total"] for row in rows}
                batch = WeeklyBatchOverview(
                    run_date=latest["run_date"],
                    status=latest["status"],
                    pending=counts.get("pending", 0),
                    completed=counts.get("completed", 0),
                    failed=counts.get("failed", 0),
                )
    return AdminOverview(
        registered_accounts=accounts,
        feedback=FeedbackOverview(
            reported=feedback.get("reported", 0),
            draft=feedback.get("draft", 0),
            approved=feedback.get("approved", 0),
            rejected=feedback.get("rejected", 0),
        ),
        weekly_batch=batch,
    )
