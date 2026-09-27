"""Build labeled ``(text, category)`` datasets for training."""

from __future__ import annotations

import csv
from pathlib import Path

from dompet.ml.features import text_from_row
from dompet.ml.synthetic import generate_dataset

SOURCES = ("synthetic", "db", "csv")


def load_dataset(
    source: str = "synthetic",
    *,
    conn=None,
    csv_path: str | Path | None = None,
    n_per_category: int = 40,
    seed: int = 42,
) -> list[tuple[str, str]]:
    """Return labeled rows. ``synthetic`` needs nothing but the stdlib."""
    if source == "synthetic":
        return generate_dataset(n_per_category=n_per_category, seed=seed)

    if source == "db":
        if conn is None:
            raise ValueError("source='db' requires a live connection")
        from dompet.db.repository import labeled_rows

        return [(text_from_row(r), r["category"]) for r in labeled_rows(conn)]

    if source == "csv":
        if not csv_path:
            raise ValueError("source='csv' requires csv_path")
        with Path(csv_path).open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            return [(r["text"], r["category"]) for r in reader]

    raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")
