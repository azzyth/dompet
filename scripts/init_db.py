"""Apply db/schema.sql, db/seed.sql, db/views.sql to the configured database.

Usage:  python scripts/init_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running a file directly puts the script's own directory on sys.path, not the repo
# root, so `python scripts/init_db.py` would not find the `dompet` package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dompet.db.connection import connect  # noqa: E402

DB_DIR = ROOT / "db"
FILES = ("schema.sql", "seed.sql", "views.sql")


def apply(conn, path: Path) -> None:
    with conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def main() -> None:
    conn = connect()
    try:
        for name in FILES:
            apply(conn, DB_DIR / name)
            print(f"applied db/{name}")
    finally:
        conn.close()
    print("database ready")


if __name__ == "__main__":
    main()
