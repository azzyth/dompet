"""Seed the database with synthetic transactions for a public demo.

Lets the deployed dashboard show a realistic tracker without exposing any real
bank data. Every row goes through the same parse -> categorize -> store pipeline
as a genuine notification, so the demo exercises the real code path.

Usage:  python scripts/seed_demo.py --n 250 --days 60 --seed 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Running a file directly puts the script's own directory on sys.path, not the repo
# root, so `python scripts/seed_demo.py` would not find the `dompet` package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dompet.db.connection import connect  # noqa: E402
from dompet.ingest import ingest_many  # noqa: E402
from dompet.ml.synthetic import generate_notifications  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=250, help="number of notifications")
    parser.add_argument("--days", type=int, default=60, help="spread over the past N days")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    items = generate_notifications(args.n, days=args.days, seed=args.seed)
    conn = connect()
    try:
        summary = ingest_many(conn, items, source="demo")
    finally:
        conn.close()
    print("seeded demo data:", summary)


if __name__ == "__main__":
    main()
