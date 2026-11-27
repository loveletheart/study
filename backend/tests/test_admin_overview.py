import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.common.database import connect_database, initialize_database
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore
from app.outfits.infrastructure.weekly_batch import WeeklyBatchStore
from app.users.application.dto import AdminOverview, FeedbackOverview, WeeklyBatchHistoryEntry, WeeklyBatchOverview
from app.users.infrastructure.admin_overview import read_admin_overview


class AdminOverviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "overview.db"
        initialize_database(self.path)

    def test_empty_database_does_not_require_outfit_tables(self):
        self.assertEqual(
            read_admin_overview(self.path),
            AdminOverview(0, FeedbackOverview(0, 0, 0, 0), None),
        )

    def test_groups_feedback_and_keeps_each_batch_run_separate(self):
        SQLiteFeedbackStore(self.path).generations()
        WeeklyBatchStore(self.path, "current", lambda: datetime.now(timezone.utc))
        with closing(connect_database(self.path)) as connection, connection:
            connection.executemany(
                "INSERT INTO users (id, name, email) VALUES (?, ?, ?)",
                [("account", "Account", "account@example.com"), ("legacy", "Legacy", "legacy@example.com")],
            )
            connection.execute("INSERT INTO user_credentials VALUES ('account', 'test-hash')")
            connection.execute(
                "INSERT INTO outfit_generations "
                "(id, created_at, source_kind, exact_prompt, provider, model, prompt_version, "
                "request_json, raw_response, schema_valid) "
                "VALUES ('g', '2026-11-27', 'app_request', 1, 'test', 'test', '1', '{}', '{}', 1)",
            )
            connection.executemany(
                "INSERT INTO outfit_feedback "
                "(id, generation_id, owner_id, date, issues_json, note, status, revision, created_at, updated_at) "
                "VALUES (?, 'g', 'account', ?, '[]', '', ?, 1, '2026-11-27', '2026-11-27')",
                [(str(index), f"2026-11-{index:02}", status) for index, status in enumerate(
                    ("reported", "reported", "draft", "approved", "rejected"), start=1,
                )],
            )
            connection.executemany(
                "INSERT INTO outfit_weekly_batch_runs (scope, run_date, started_at, finished_at, status) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    *(("current", f"2026-11-{day}", 1, 2, "completed") for day in range(21, 27)),
                    ("previous", "2026-11-27", 2, 3, "partial_failure"),
                    ("current", "2026-11-27", 3, None, "running"),
                ],
            )
            connection.executemany(
                "INSERT INTO outfit_weekly_batch_targets "
                "(scope, run_date, kind, latitude, longitude, requested_at, status) "
                "VALUES (?, ?, 'weekly', ?, 127, 0, ?)",
                [
                    ("current", "2026-11-26", 37, "completed"),
                    ("previous", "2026-11-27", 37, "completed"),
                    ("current", "2026-11-27", 37, "pending"),
                    ("current", "2026-11-27", 38, "completed"),
                    ("current", "2026-11-27", 39, "failed"),
                    ("current", "2026-11-27", 40, "failed"),
                ],
            )

        overview = read_admin_overview(self.path)
        self.assertEqual(overview.registered_accounts, 1)
        self.assertEqual(overview.feedback, FeedbackOverview(2, 1, 1, 1))
        latest = WeeklyBatchOverview("2026-11-27", "running", 1, 1, 2)
        self.assertEqual(overview.weekly_batch, latest)
        history = overview.weekly_batch_history
        self.assertEqual([entry.batch.run_date for entry in history], [
            "2026-11-27", "2026-11-27", "2026-11-26", "2026-11-25", "2026-11-24", "2026-11-23", "2026-11-22",
        ])
        self.assertEqual(history[0], WeeklyBatchHistoryEntry(latest, datetime.fromtimestamp(3, timezone.utc), None))
        self.assertEqual(history[1], WeeklyBatchHistoryEntry(
            WeeklyBatchOverview("2026-11-27", "partial_failure", 0, 1, 0),
            datetime.fromtimestamp(2, timezone.utc),
            datetime.fromtimestamp(3, timezone.utc),
        ))
        self.assertEqual(history[2].batch, WeeklyBatchOverview("2026-11-26", "completed", 0, 1, 0))
        self.assertEqual(history[3].batch, WeeklyBatchOverview("2026-11-25", "completed", 0, 0, 0))
