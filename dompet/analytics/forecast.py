"""End-of-month balance forecasting. Pure stdlib.

The model is deliberately simple and honest: a personal cashflow has far too few
data points to justify anything heavier, and a robust daily-rate projection is
easy to explain and hard to fool. Three methods are offered so the choice is
explicit rather than hidden:

  mean     — average daily net over the lookback window (includes zero-spend days)
  median   — same window, median daily net (resistant to one big purchase)
  weekday  — per-weekday average net, so weekend-heavy spending is priced in
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean, median

ZERO = Decimal("0")
METHODS = ("mean", "median", "weekday")


@dataclass
class Forecast:
    as_of: date
    month_end: date
    method: str
    current_balance: Decimal
    avg_daily_net: Decimal
    remaining_days: int
    projected_balance: Decimal
    days_until_zero: int | None

    def as_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "month_end": self.month_end.isoformat(),
            "method": self.method,
            "current_balance": str(self.current_balance),
            "avg_daily_net": str(self.avg_daily_net),
            "remaining_days": self.remaining_days,
            "projected_balance": str(self.projected_balance),
            "days_until_zero": self.days_until_zero,
        }


def month_end(as_of: date) -> date:
    if as_of.month == 12:
        return date(as_of.year, 12, 31)
    return date(as_of.year, as_of.month + 1, 1) - timedelta(days=1)


def net_by_day(transactions: Iterable) -> dict[date, Decimal]:
    """Collapse transactions into a ``{day: signed net}`` mapping."""
    out: dict[date, Decimal] = {}
    for tx in transactions:
        day = tx.posted_at.date()
        out[day] = out.get(day, ZERO) + tx.signed_amount
    return out


def _window_values(series: Mapping[date, Decimal], as_of: date, lookback_days: int) -> list[Decimal]:
    start = as_of - timedelta(days=lookback_days - 1)
    return [series.get(start + timedelta(days=i), ZERO) for i in range(lookback_days)]


def _weekday_rates(series: Mapping[date, Decimal], as_of: date, lookback_days: int) -> dict[int, Decimal]:
    buckets: dict[int, list[Decimal]] = {i: [] for i in range(7)}
    start = as_of - timedelta(days=lookback_days - 1)
    for i in range(lookback_days):
        day = start + timedelta(days=i)
        buckets[day.weekday()].append(series.get(day, ZERO))
    return {wd: (mean(vals) if vals else ZERO) for wd, vals in buckets.items()}


def _remaining_days(as_of: date, end: date) -> list[date]:
    return [as_of + timedelta(days=i + 1) for i in range((end - as_of).days)]


def forecast_month_end(
    daily: Mapping[date, Decimal],
    *,
    current_balance: Decimal,
    as_of: date | None = None,
    method: str = "mean",
    lookback_days: int = 30,
) -> Forecast:
    """Project the balance at month end from a daily-net series."""
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; expected one of {METHODS}")

    as_of = as_of or date.today()
    end = month_end(as_of)
    series = {day: Decimal(str(net)) for day, net in daily.items()}
    remaining = _remaining_days(as_of, end)

    if method == "weekday":
        rates = _weekday_rates(series, as_of, lookback_days)
        expected = sum((rates[d.weekday()] for d in remaining), ZERO)
        avg_daily = (
            Decimal(str(mean([r for r in rates.values()]))) if rates else ZERO
        )
    else:
        values = _window_values(series, as_of, lookback_days)
        avg_daily = Decimal(str(mean(values))) if method == "mean" else Decimal(str(median(values)))
        expected = avg_daily * len(remaining)

    projected = Decimal(str(current_balance)) + expected

    days_until_zero: int | None = None
    if avg_daily < 0 and current_balance > 0:
        days_until_zero = int(Decimal(str(current_balance)) / (avg_daily * -1))

    return Forecast(
        as_of=as_of,
        month_end=end,
        method=method,
        current_balance=Decimal(str(current_balance)),
        avg_daily_net=avg_daily,
        remaining_days=len(remaining),
        projected_balance=projected,
        days_until_zero=days_until_zero,
    )
