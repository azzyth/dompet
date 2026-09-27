"""Load the seed keyword rules (dompet/ml/labels.py) into the category_rules table.

Usage:  python scripts/load_rules.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running a file directly puts the script's own directory on sys.path, not the repo
# root, so `python scripts/load_rules.py` would not find the `dompet` package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dompet.db.connection import connect  # noqa: E402
from dompet.db.repository import replace_seed_rules  # noqa: E402
from dompet.ml.labels import SEED_RULES  # noqa: E402


def main() -> None:
    conn = connect()
    try:
        n = replace_seed_rules(conn, SEED_RULES)
    finally:
        conn.close()
    print(f"loaded {n} seed rules")


if __name__ == "__main__":
    main()
