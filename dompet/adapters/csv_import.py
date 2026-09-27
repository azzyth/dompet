"""CSV statement importer — for backfilling history from a bank e-statement export.

Bank exports differ, so columns are configurable. Each row is stored as a
``raw_notification`` (a canonical line built from the columns) before becoming a
transaction, which means re-importing the same statement is idempotent via the
same ``content_hash`` machinery as every other source.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from dompet.core.models import Direction, Transaction
from dompet.core.normalize import normalize_merchant, parse_amount, parse_datetime, raw_hash
from dompet.core.parsers.common import detect_channel
from dompet.db import repository as repo
from dompet.ingest import build_categorizer


def _parse_date(value: str) -> datetime:
    dt = parse_datetime(value)
    if dt:
        return dt
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {value!r}")


def import_csv(
    conn,
    path: str | Path,
    *,
    source: str = "csv",
    account_label: str = "unknown",
    date_col: str = "date",
    desc_col: str = "description",
    amount_col: str = "amount",
    direction_col: str | None = None,
    categorizer=None,
) -> dict[str, int]:
    """Import a statement CSV. Returns the same summary shape as other ingest paths."""
    categorize = categorizer or build_categorizer(conn)
    summary = {"seen": 0, "created": 0, "duplicate": 0, "unparsed": 0}
    account_id = repo.get_account_id(conn, account_label)
    cats = repo.category_ids(conn)

    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            summary["seen"] += 1
            try:
                description = (row.get(desc_col) or "").strip()
                amount = parse_amount(row.get(amount_col, ""))
                if amount is None or amount == 0:
                    summary["unparsed"] += 1
                    continue
                if direction_col and row.get(direction_col):
                    direction = (
                        Direction.CREDIT
                        if str(row[direction_col]).strip().lower().startswith("c")
                        else Direction.DEBIT
                    )
                else:
                    direction = Direction.CREDIT if amount > 0 else Direction.DEBIT
                amount = abs(amount)
                posted_at = _parse_date(row.get(date_col, ""))
            except (ValueError, TypeError, KeyError):
                summary["unparsed"] += 1
                continue

            raw_text = f"{account_label} | {posted_at.date().isoformat()} | {description} | {amount}"
            raw_id = repo.insert_raw(
                conn,
                source=source,
                received_at=posted_at,
                raw_text=raw_text,
                content_hash=raw_hash(raw_text),
            )
            if raw_id is None:
                summary["duplicate"] += 1
                continue

            merchant = normalize_merchant(description)
            tx = Transaction(
                posted_at=posted_at,
                amount=amount,
                direction=direction,
                description=description,
                source=source,
                account_label=account_label,
                channel=detect_channel(description),
                merchant_raw=merchant,
                raw_text=raw_text,
            )
            category, confidence, _method = categorize(tx)
            repo.insert_transaction(
                conn,
                tx=tx,
                account_id=account_id,
                raw_id=raw_id,
                merchant_id=repo.get_or_create_merchant(conn, merchant),
                category_id=cats.get(category, cats.get("Other")),
                confidence=confidence,
            )
            repo.mark_raw(conn, raw_id, processed=True)
            conn.commit()
            summary["created"] += 1

    repo.log_ingestion(
        conn,
        source=source,
        seen=summary["seen"],
        parsed=summary["created"],
        skipped=summary["duplicate"],
        errors=summary["unparsed"],
        note=str(path),
    )
    conn.commit()
    return summary
