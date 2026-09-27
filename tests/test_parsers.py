"""Manifest-driven parser tests over the notification fixture corpus."""

from __future__ import annotations

import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dompet.core import parse
from dompet.core.parsers.registry import detect_source

FIXTURES = Path(__file__).parent / "fixtures" / "notifications"


class ParserFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
        cls.received_at = datetime.fromisoformat(cls.manifest["received_at"])
        cls.cases = cls.manifest["cases"]

    def test_manifest_lists_every_fixture(self):
        files = {p.name for p in FIXTURES.glob("*.txt")}
        listed = {c["file"] for c in self.cases}
        self.assertEqual(files, listed, "manifest.json and *.txt fixtures are out of sync")
        self.assertTrue(files, "expected at least one fixture notification")

    def test_fixtures_parse_to_expected_fields(self):
        for case in self.cases:
            with self.subTest(fixture=case["file"]):
                text = (FIXTURES / case["file"]).read_text(encoding="utf-8")

                self.assertEqual(detect_source(text), case["source"])

                tx = parse(text, self.received_at)
                self.assertIsNotNone(tx, "fixture failed to parse")
                assert tx is not None  # for type checkers

                self.assertEqual(tx.amount, Decimal(case["amount"]))
                self.assertEqual(tx.direction.value, case["direction"])
                self.assertEqual(tx.account_label, case["account"])
                self.assertEqual(tx.channel.value, case["channel"])
                self.assertEqual(tx.merchant_raw, case["merchant"])

    def test_unparseable_text_returns_none(self):
        self.assertIsNone(parse("Your OTP is 123456. Do not share it.", self.received_at))
        self.assertIsNone(parse("Good morning! Have a nice day.", self.received_at))


if __name__ == "__main__":
    unittest.main()
