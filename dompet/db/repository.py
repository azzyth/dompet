"""Raw-SQL repository. Every read and write the service performs lives here.

Deliberately hand-written SQL (no ORM): the query text is the deliverable, and the
reporting reads go through the views in ``db/views.sql``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from dompet.core.models import Transaction
from dompet.core.rules import Rule


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
def get_account_id(conn, label: str, kind: str = "bank") -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accounts (label, kind) VALUES (%s, %s)
            ON CONFLICT (label) DO UPDATE SET label = EXCLUDED.label
            RETURNING id
            """,
            (label, kind),
        )
        return cur.fetchone()["id"]


def get_or_create_merchant(conn, canonical: str | None) -> int | None:
    if not canonical:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO merchants (canonical_name) VALUES (%s)
            ON CONFLICT (canonical_name) DO UPDATE SET canonical_name = EXCLUDED.canonical_name
            RETURNING id
            """,
            (canonical,),
        )
        return cur.fetchone()["id"]


def category_ids(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT name, id FROM categories")
        return {row["name"]: row["id"] for row in cur.fetchall()}


def load_rules(conn) -> list[Rule]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.pattern, c.name AS category, r.priority
            FROM category_rules r
            JOIN categories c ON c.id = r.category_id
            ORDER BY r.priority, c.name
            """
        )
        return [Rule(row["pattern"], row["category"], row["priority"]) for row in cur.fetchall()]


def replace_seed_rules(conn, rules: Iterable[Rule]) -> int:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM category_rules WHERE source = 'seed'")
        n = 0
        for rule in rules:
            cur.execute(
                """
                INSERT INTO category_rules (pattern, category_id, priority, source)
                SELECT %s, id, %s, 'seed' FROM categories WHERE name = %s
                """,
                (rule.pattern, rule.priority, rule.category),
            )
            n += cur.rowcount
        conn.commit()
        return n


# --------------------------------------------------------------------------- #
# Ingestion writes
# --------------------------------------------------------------------------- #
def insert_raw(
    conn, *, source: str, received_at: datetime, raw_text: str, content_hash: str
) -> int | None:
    """Insert a notification, or return ``None`` if it was already seen."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw_notifications (source, received_at, raw_text, content_hash)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id
            """,
            (source, received_at, raw_text, content_hash),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def mark_raw(conn, raw_id: int, *, processed: bool, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE raw_notifications SET processed = %s, parse_error = %s WHERE id = %s",
            (processed, error, raw_id),
        )


def insert_transaction(
    conn,
    *,
    tx: Transaction,
    account_id: int,
    raw_id: int | None,
    merchant_id: int | None,
    category_id: int | None,
    confidence: float | None,
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO transactions
                (account_id, raw_id, posted_at, amount, direction, channel, currency,
                 merchant_id, description, category_id, confidence, external_ref)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (raw_id) DO NOTHING
            RETURNING id
            """,
            (
                account_id,
                raw_id,
                tx.posted_at,
                tx.amount,
                tx.direction.value,
                tx.channel.value,
                tx.currency,
                merchant_id,
                tx.description,
                category_id,
                confidence,
                tx.external_ref,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def log_ingestion(
    conn, *, source: str, seen: int, parsed: int, skipped: int, errors: int, note: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_log (source, n_seen, n_parsed, n_skipped, n_errors, note)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (source, seen, parsed, skipped, errors, note),
        )


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
def monthly_category_spend(conn, limit: int = 200) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT month, category, total, n_tx, avg_tx FROM v_monthly_category_spend LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def merchant_rollup(conn, limit: int = 20) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT merchant, category, total, n_tx, last_seen FROM v_merchant_rollup LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def burn_rate(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT avg_daily_spend, projected_monthly_spend, days_with_spend, days_observed
            FROM v_burn_rate
            """
        )
        return cur.fetchone() or {
            "avg_daily_spend": None,
            "projected_monthly_spend": None,
            "days_with_spend": 0,
            "days_observed": 0,
        }


def source_mix(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT source, n_tx, first_seen, last_seen FROM v_source_mix")
        return cur.fetchall()


def review_queue(conn, limit: int = 50, *, below: float = 0.5) -> list[dict]:
    """Only the rows that actually need a human: uncategorized/uncertain, not reviewed.

    (Filtering on `is_reviewed` alone returns the entire table, since nothing is ever
    auto-marked as reviewed — the queue must be confidence-driven to be useful.)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.posted_at, t.amount, t.direction, t.channel, t.confidence,
                   t.description,
                   a.label AS account, m.canonical_name AS merchant, c.name AS category
            FROM transactions t
            LEFT JOIN accounts  a ON a.id = t.account_id
            LEFT JOIN merchants m ON m.id = t.merchant_id
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE NOT t.is_reviewed
              AND (t.confidence IS NULL OR t.confidence < %s)
            ORDER BY t.confidence ASC NULLS FIRST, t.posted_at DESC
            LIMIT %s
            """,
            (below, limit),
        )
        return cur.fetchall()


def daily_cashflow(conn, days: int = 90) -> list[tuple[date, Decimal]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT day, net FROM v_daily_net_cashflow
            WHERE day >= current_date - %s::int
            ORDER BY day
            """,
            (days,),
        )
        return [(row["day"], row["net"]) for row in cur.fetchall()]


def current_balance(conn) -> Decimal:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(signed_amount), 0) AS bal FROM v_signed_transactions")
        return cur.fetchone()["bal"]


def list_transactions(conn, limit: int = 50, *, unreviewed_only: bool = False) -> list[dict]:
    where = "WHERE NOT t.is_reviewed" if unreviewed_only else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT t.id, t.posted_at, t.amount, t.direction, t.channel, t.description,
                   t.confidence, t.is_reviewed, rn.source AS source,
                   a.label AS account, m.canonical_name AS merchant, c.name AS category
            FROM transactions t
            LEFT JOIN raw_notifications rn ON rn.id = t.raw_id
            LEFT JOIN accounts  a ON a.id = t.account_id
            LEFT JOIN merchants m ON m.id = t.merchant_id
            LEFT JOIN categories c ON c.id = t.category_id
            {where}
            ORDER BY t.posted_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cur.fetchall()


def set_category(conn, tx_id: int, category: str, *, reviewed: bool = True) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE transactions
            SET category_id = (SELECT id FROM categories WHERE name = %s),
                is_reviewed = %s
            WHERE id = %s
            """,
            (category, reviewed, tx_id),
        )
        return cur.rowcount


def save_forecast(conn, rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO forecasts (horizon_day, predicted_balance, model_version)
                VALUES (%s, %s, %s)
                """,
                (row["horizon_day"], row["predicted_balance"], row.get("model_version", "v0")),
            )
            n += 1
        conn.commit()
        return n


def labeled_rows(conn) -> list[dict]:
    """Reviewed / confidently categorized rows for supervised training."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.description, t.channel, m.canonical_name AS merchant, c.name AS category
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            LEFT JOIN merchants m ON m.id = t.merchant_id
            WHERE c.name <> 'Other'
              AND (t.is_reviewed OR t.confidence >= 0.5)
            """
        )
        return cur.fetchall()
