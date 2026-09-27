"""Poll the configured IMAP inbox and ingest any new notifications.

Usage:  python scripts/poll_inbox.py
Requires IMAP_* and DATABASE_URL in the environment (see .env.example).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running a file directly puts the script's own directory on sys.path, not the repo
# root, so `python scripts/poll_inbox.py` would not find the `dompet` package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dompet.adapters.imap import poll_once  # noqa: E402


def main() -> None:
    summary = poll_once()
    print(
        "polled {seen} messages: {created} created, {duplicate} duplicate, {unparsed} unparsed".format(
            **summary
        )
    )


if __name__ == "__main__":
    main()
