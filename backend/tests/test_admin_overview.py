import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.common.database import connect_database, initialize_database
from app.outfits.infrastructure.feedback import SQLiteFeedbackStore
from app.outfits.infrastructure.weekly_batch import WeeklyBatchStore
from app.users.application.dto import AdminOverview, FeedbackOverview, WeeklyBatchOverview
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

    def test_groups_feedback_and_uses_only_latest_batch_targets(self):
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
                "INSERT INTO outfit_weekly_batch_runs (scope, run_date, started_at, status) VALUES (?, ?, ?, ?)",
                [
                    ("current", "2026-11-26", 1, "completed"),
                    ("previous", "2026-11-27", 2, "completed"),
                    ("current", "2026-11-27", 3, "running"),
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

        self.assertEqual(
            read_admin_overview(self.path),
            AdminOverview(1, FeedbackOverview(2, 1, 1, 1), WeeklyBatchOverview("2026-11-27", "running", 1, 1, 2)),
        )
