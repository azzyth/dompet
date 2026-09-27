"""Idempotency: re-ingesting the same notification must be a no-op.

The DB enforces this with `raw_notifications.content_hash UNIQUE` and
`transactions.raw_id UNIQUE`; these tests pin the hashes that back those
constraints so a regression in the parsers cannot silently create duplicates.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from dompet.core import parse
from dompet.core.models import RawNotification

FIXTURES = Path(__file__).parent / "fixtures" / "notifications"


class IdempotencyTest(unittest.TestCase):
    def setUp(self):
        self.received_at = datetime(2026, 9, 24, 18, 0, 0)
        self.text = (FIXTURES / "gopay.txt").read_text(encoding="utf-8")

    def test_repeat_notification_hash_is_stable(self):
        a = RawNotification("imap", self.text, self.received_at)
        b = RawNotification("imap", self.text + "\n", datetime(2026, 9, 25, 9, 0, 0))
        self.assertEqual(a.content_hash, b.content_hash)

    def test_repeat_parse_yields_identical_transaction_hash(self):
        first = parse(self.text, self.received_at)
        second = parse(self.text, self.received_at)
        assert first is not None and second is not None
        self.assertEqual(first.content_hash, second.content_hash)

    def test_different_notifications_hash_differently(self):
        other = (FIXTURES / "ovo.txt").read_text(encoding="utf-8")
        a = parse(self.text, self.received_at)
        b = parse(other, self.received_at)
        assert a is not None and b is not None
        self.assertNotEqual(a.content_hash, b.content_hash)


if __name__ == "__main__":
    unittest.main()
