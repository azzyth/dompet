"""Synthetic data must be internally consistent.

Regression: the generator picked the date embedded in each notification text
independently of the timestamp it was "received", so seeded demo rows landed in the
future relative to the import — which leaked into the trailing-30-day burn window
(days_with_spend could exceed days_observed).
"""

from __future__ import annotations

import unittest
from datetime import datetime

from dompet.core import parse
from dompet.ml.synthetic import generate_dataset, generate_notifications


class GenerateNotificationsTest(unittest.TestCase):
    def setUp(self):
        self.end = datetime(2026, 9, 24, 12, 0, 0)
        self.items = generate_notifications(n=120, days=45, seed=3, end=self.end)

    def test_count_and_order(self):
        self.assertEqual(len(self.items), 120)
        self.assertEqual(self.items, sorted(self.items, key=lambda r: r[1]))

    def test_nothing_is_future_dated(self):
        for text, received in self.items:
            with self.subTest(text=text):
                self.assertLessEqual(received, self.end)
                tx = parse(text, received)
                self.assertIsNotNone(tx, "generated notification did not parse")
                assert tx is not None
                self.assertLessEqual(tx.posted_at, self.end, f"future-dated row: {text}")

    def test_embedded_date_matches_received_timestamp(self):
        for text, received in self.items:
            with self.subTest(text=text):
                tx = parse(text, received)
                assert tx is not None
                self.assertEqual(tx.posted_at.date(), received.date(), text)

    def test_training_dataset_is_balanced_and_parses(self):
        rows = generate_dataset(n_per_category=5, seed=1)
        self.assertEqual(len(rows), len({c for _, c in rows}) * 5)
        for text, _category in rows:
            self.assertIsNotNone(parse(text, self.end), text)


if __name__ == "__main__":
    unittest.main()
