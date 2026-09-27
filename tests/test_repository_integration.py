"""DB-backed integration test for every repository read path.

Skips unless ``DATABASE_URL`` is set and psycopg is importable, so the stdlib suite still
runs with no services — but in CI (Postgres service, schema/seed/views loaded) it runs and
catches schema drift such as referencing a column that does not exist.

That is exactly the bug this guards against: ``list_transactions`` selected
``transactions.source``, which only exists on ``raw_notifications``, so ``GET /transactions``
returned 500 while every unit test and the ``/health`` smoke test stayed green. Every read
path is executed here so a broken query cannot hide behind an untested endpoint.

Run it directly against the compose stack with:

    docker compose exec -T api python -m unittest tests.test_repository_integration -v
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime

try:
    import psycopg  # noqa: F401

    HAVE_PSYCOPG = True
except ImportError:
    HAVE_PSYCOPG = False

REQUIRES_DB = unittest.skipUnless(
    HAVE_PSYCOPG and os.environ.get("DATABASE_URL"),
    "needs psycopg and a DATABASE_URL",
)


@REQUIRES_DB
class RepositoryReadPathsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dompet.db.connection import connect

        cls.conn = connect()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_every_read_path_executes(self):
        """Each query must run against the real schema — no undefined columns."""
        from dompet.db import repository as repo

        self.assertIsInstance(repo.category_ids(self.conn), dict)
        self.assertIsInstance(repo.load_rules(self.conn), list)
        self.assertIsInstance(repo.monthly_category_spend(self.conn), list)
        self.assertIsInstance(repo.merchant_rollup(self.conn, 5), list)
        self.assertIsInstance(repo.burn_rate(self.conn), dict)
        self.assertIsInstance(repo.daily_cashflow(self.conn, 30), list)
        self.assertIsInstance(repo.current_balance(self.conn), object)
        self.assertIsInstance(repo.list_transactions(self.conn, 5), list)
        self.assertIsInstance(
            repo.list_transactions(self.conn, 5, unreviewed_only=True), list
        )

    def test_list_transactions_exposes_ingestion_source(self):
        """Regression: source is read via raw_notifications, not transactions."""
        from dompet.db import repository as repo

        for row in repo.list_transactions(self.conn, 5):
            self.assertIn("source", row)

    def test_burn_rate_uses_the_calendar_window(self):
        """Invariant: quiet days count as zero spend, so the denominator is the window."""
        from dompet.db import repository as repo

        burn = repo.burn_rate(self.conn)
        self.assertEqual(burn["days_observed"], 30)
        self.assertIn("days_with_spend", burn)
        # Regression: future-dated rows once pushed this above the window size.
        self.assertLessEqual(burn["days_with_spend"], burn["days_observed"])

    def test_ingest_round_trip_is_idempotent(self):
        """The UNIQUE constraints must make a re-ingest a no-op, end to end."""
        from dompet.core.normalize import raw_hash
        from dompet.ingest import ingest_many

        text = "BCA: TRK 999001 TGL 24/09 17:01:23 di TOKEDOMPETTEST QRIS"
        received = datetime(2026, 9, 24, 17, 1, 23)
        self.addCleanup(self._cleanup, raw_hash(text))

        first = ingest_many(self.conn, [(text, received)], source="unittest")
        second = ingest_many(self.conn, [(text, received)], source="unittest")

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["duplicate"], 1)

    def _cleanup(self, content_hash: str) -> None:
        """Remove rows this test wrote, so a local run cannot pollute the demo data."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM transactions
                WHERE raw_id IN (SELECT id FROM raw_notifications WHERE content_hash = %s)
                """,
                (content_hash,),
            )
            cur.execute("DELETE FROM raw_notifications WHERE content_hash = %s", (content_hash,))
        self.conn.commit()


if __name__ == "__main__":
    unittest.main()
