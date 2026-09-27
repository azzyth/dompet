"""Categorization order: rules -> ML -> Other.

Pins the invariant that keyword rules always win over the model, the model is
consulted only when no rule matches, and a missing model degrades to ``Other``
rather than erroring. Uses a stub model so no trained artifact or DB is needed.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from dompet.core.models import Channel, Direction, Transaction
from dompet.ingest import build_categorizer


class _StubModel:
    """Minimal stand-in for dompet.ml.predict.CategoryModel."""

    def __init__(self, label: str, confidence: float):
        self.label = label
        self.confidence = confidence

    def predict(self, text: str) -> tuple[str, float]:
        return self.label, self.confidence


def _tx(merchant: str, description: str) -> Transaction:
    return Transaction(
        posted_at=datetime(2026, 9, 24, 17, 1, 23),
        amount=Decimal("50000"),
        direction=Direction.DEBIT,
        description=description,
        merchant_raw=merchant,
        channel=Channel.QRIS,
    )


class CategorizerOrderTest(unittest.TestCase):
    def test_rule_beats_model(self):
        # "GAJI" is rule-matched Income; the stub model (wrongly) says Shopping.
        categorizer = build_categorizer(None, _StubModel("Shopping", 0.99))
        self.assertEqual(
            categorizer(_tx("GAJI BULANAN", "TRSF E-BANKING CR GAJI BULANAN")),
            ("Income", 1.0, "rule"),
        )

    def test_model_used_when_no_rule_matches(self):
        # No seed rule matches this merchant, so the model must be consulted.
        categorizer = build_categorizer(None, _StubModel("Shopping", 0.42))
        self.assertEqual(
            categorizer(_tx("TOKO ELEKTRONIK JAYA", "pembayaran QRIS di TOKO ELEKTRONIK JAYA")),
            ("Shopping", 0.42, "model"),
        )

    def test_other_fallback_without_model(self):
        categorizer = build_categorizer(None, None)
        self.assertEqual(
            categorizer(_tx("TOKO ELEKTRONIK JAYA", "pembayaran QRIS di TOKO ELEKTRONIK JAYA")),
            ("Other", 0.0, "fallback"),
        )

    def test_categorizer_works_without_a_database(self):
        # conn=None must fall back to the in-code SEED_RULES, not raise.
        categorizer = build_categorizer(None)
        self.assertEqual(categorizer(_tx("KOPI KENANGAN", "Pembayaran ke KOPI KENANGAN"))[2], "rule")


if __name__ == "__main__":
    unittest.main()
