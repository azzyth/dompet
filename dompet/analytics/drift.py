"""Category drift detection. Pure stdlib.

Uses a robust z-score (median + median absolute deviation) instead of mean/std so
a single large purchase does not permanently widen the "normal" band. An alert
means: this category's spend is unusual *for this person's own history*.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

SATURATED_Z = 99.0  # used when history has zero spread but the value differs


@dataclass
class DriftAlert:
    category: str
    current: Decimal
    baseline_median: Decimal
    robust_z: float
    direction: str  # "up" | "down"

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "current": str(self.current),
            "baseline_median": str(self.baseline_median),
            "robust_z": round(self.robust_z, 3),
            "direction": self.direction,
        }


def median_abs_deviation(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    med = median(values)
    return float(median([abs(v - med) for v in values]))


def robust_z(value: float, history: Sequence[float]) -> float:
    """Robust z-score. Saturates at :data:`SATURATED_Z` when MAD is zero."""
    if not history:
        return 0.0
    med = float(median(history))
    mad = median_abs_deviation(history)
    if mad == 0:
        return 0.0 if value == med else SATURATED_Z
    return 0.6745 * (value - med) / mad


def detect_drift(
    current: Mapping[str, Decimal],
    history: Mapping[str, Sequence[Decimal]],
    *,
    threshold: float = 3.5,
    min_history: int = 3,
) -> list[DriftAlert]:
    """Return alerts for categories whose current value is far from their own history."""
    alerts: list[DriftAlert] = []
    for category, value in current.items():
        past = [float(v) for v in history.get(category, ())]
        if len(past) < min_history:
            continue
        z = robust_z(float(value), past)
        if abs(z) >= threshold:
            alerts.append(
                DriftAlert(
                    category=category,
                    current=Decimal(str(value)),
                    baseline_median=Decimal(str(median(past))),
                    robust_z=z,
                    direction="up" if z > 0 else "down",
                )
            )
    alerts.sort(key=lambda a: abs(a.robust_z), reverse=True)
    return alerts
