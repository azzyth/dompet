"""Forecast math."""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from dompet.analytics.forecast import Forecast, forecast_month_end, month_end, net_by_day


class _Tx:
    def __init__(self, day: date, amount: str):
        self.posted_at = datetime.combine(day, time(12, 0))
        self.signed_amount = Decimal(amount)


class MonthEndTest(unittest.TestCase):
    def test_mid_year(self):
        self.assertEqual(month_end(date(2026, 9, 15)), date(2026, 9, 30))

    def test_february_leap(self):
        self.assertEqual(month_end(date(2028, 2, 3)), date(2028, 2, 29))

    def test_december(self):
        self.assertEqual(month_end(date(2026, 12, 10)), date(2026, 12, 31))


class NetByDayTest(unittest.TestCase):
    def test_aggregates_same_day(self):
        d = date(2026, 9, 3)
        series = net_by_day([_Tx(d, "-50000"), _Tx(d, "-25000"), _Tx(d, "200000")])
        self.assertEqual(series[d], Decimal("125000"))


class ForecastTest(unittest.TestCase):
    def setUp(self):
        self.as_of = date(2026, 9, 15)
        self.daily = {
            self.as_of - timedelta(days=i): Decimal("-100000") for i in range(30)
        }

    def test_mean_projection_and_zero_day(self):
        f = forecast_month_end(
            self.daily, current_balance=Decimal("1000000"), as_of=self.as_of, method="mean"
        )
        self.assertIsInstance(f, Forecast)
        self.assertEqual(f.month_end, date(2026, 9, 30))
        self.assertEqual(f.remaining_days, 15)
        self.assertEqual(f.avg_daily_net, Decimal("-100000"))
        self.assertEqual(f.projected_balance, Decimal("-500000"))
        self.assertEqual(f.days_until_zero, 10)

    def test_zero_days_are_included_in_the_rate(self):
        # Spend on only 15 of the last 30 days must halve the daily rate.
        sparse = {self.as_of - timedelta(days=i): Decimal("-100000") for i in range(0, 30, 2)}
        f = forecast_month_end(
            sparse, current_balance=Decimal("1000000"), as_of=self.as_of, method="mean"
        )
        self.assertEqual(f.avg_daily_net, Decimal("-50000"))

    def test_median_resists_one_big_purchase(self):
        heavy = dict(self.daily)
        heavy[self.as_of - timedelta(days=1)] = Decimal("-5000000")
        mean_f = forecast_month_end(
            heavy, current_balance=Decimal("1000000"), as_of=self.as_of, method="mean"
        )
        median_f = forecast_month_end(
            heavy, current_balance=Decimal("1000000"), as_of=self.as_of, method="median"
        )
        self.assertLess(mean_f.projected_balance, median_f.projected_balance)
        self.assertEqual(median_f.avg_daily_net, Decimal("-100000"))

    def test_weekday_matches_mean_on_flat_data(self):
        mean_f = forecast_month_end(
            self.daily, current_balance=Decimal("0"), as_of=self.as_of, method="mean"
        )
        weekday_f = forecast_month_end(
            self.daily, current_balance=Decimal("0"), as_of=self.as_of, method="weekday"
        )
        self.assertEqual(weekday_f.projected_balance, mean_f.projected_balance)

    def test_positive_cashflow_has_no_zero_day(self):
        daily = {self.as_of - timedelta(days=i): Decimal("50000") for i in range(30)}
        f = forecast_month_end(daily, current_balance=Decimal("0"), as_of=self.as_of)
        self.assertIsNone(f.days_until_zero)

    def test_unknown_method_rejected(self):
        with self.assertRaises(ValueError):
            forecast_month_end(self.daily, current_balance=Decimal("0"), method="magic")

    def test_serializes_to_json_safe_dict(self):
        f = forecast_month_end(self.daily, current_balance=Decimal("1000000"), as_of=self.as_of)
        d = f.as_dict()
        self.assertEqual(d["projected_balance"], "-500000")
        self.assertEqual(d["as_of"], "2026-09-15")


if __name__ == "__main__":
    unittest.main()
