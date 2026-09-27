"""Robust drift detection."""

from __future__ import annotations

import unittest
from decimal import Decimal

from dompet.analytics.drift import detect_drift, median_abs_deviation, robust_z


class RobustZTest(unittest.TestCase):
    def test_zero_mad_and_equal_value(self):
        self.assertEqual(robust_z(100.0, [100.0, 100.0, 100.0]), 0.0)

    def test_zero_mad_and_different_value_saturates(self):
        self.assertEqual(robust_z(250.0, [100.0, 100.0, 100.0]), 99.0)

    def test_outlier_is_large(self):
        history = [100.0, 105.0, 98.0, 102.0, 101.0]
        self.assertGreater(abs(robust_z(500.0, history)), 3.5)
        self.assertLess(abs(robust_z(103.0, history)), 3.5)

    def test_mad(self):
        self.assertEqual(median_abs_deviation([1, 1, 2, 2, 4, 6, 9]), 1.0)


class DetectDriftTest(unittest.TestCase):
    def test_flags_upward_drift_only(self):
        current = {"M1": Decimal("100000"), "M6": Decimal("900000")}
        history = {
            k: [Decimal("100000"), Decimal("110000"), Decimal("95000"), Decimal("105000")]
            for k in current
        }
        alerts = detect_drift(current, history)
        self.assertEqual([a.category for a in alerts], ["M6"])
        self.assertEqual(alerts[0].direction, "up")

    def test_skips_categories_with_too_little_history(self):
        current = {"New": Decimal("999999")}
        history = {"New": [Decimal("1")]}
        self.assertEqual(detect_drift(current, history, min_history=3), [])

    def test_alert_is_json_safe(self):
        history = {"Food": [Decimal("100000")] * 4}
        current = {"Food": Decimal("900000")}
        alert = detect_drift(current, history)[0]
        d = alert.as_dict()
        self.assertEqual(d["direction"], "up")
        self.assertIsInstance(d["robust_z"], float)


if __name__ == "__main__":
    unittest.main()
