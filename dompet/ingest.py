"""Ingestion pipeline: notification text -> parsed -> categorized -> stored.

All ingestion paths (IMAP, webhook, CSV, manual paste) funnel through here, so
dedupe, parsing, and categorization behave identically no matter the source.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dompet.core import parse
from dompet.core.models import RawNotification, Transaction
from dompet.core.rules import compile_rules, match_rule
from dompet.db import repository as repo
from dompet.ml.features import transaction_text
from dompet.ml.labels import SEED_RULES

DEFAULT_CATEGORY = "Other"
LOW_CONFIDENCE_THRESHOLD = 0.5

Categorizer = Callable[[Transaction], tuple[str, float, str]]


@dataclass
class IngestResult:
    status: str  # "created" | "duplicate" | "unparsed"
    transaction_id: int | None = None
    transaction: Transaction | None = None
    category: str | None = None
    confidence: float | None = None
    method: str | None = None  # "rule" | "model" | "fallback"
    detail: str | None = None

    @property
    def needs_review(self) -> bool:
        return self.status == "created" and (
            self.confidence is None or self.confidence < LOW_CONFIDENCE_THRESHOLD
        )


def build_categorizer(conn: Any = None, model: Any = None) -> Categorizer:
    """Rules first (deterministic), then the ML model, then a safe default.

    Rules are loaded from the DB so manual corrections can be promoted to rules;
    when the table is empty (fresh install, or no DB) the in-code seed rules apply.
    """
    rules = repo.load_rules(conn) if conn is not None else []
    if not rules:
        rules = SEED_RULES
    compiled = compile_rules(rules)

    def categorize(tx: Transaction) -> tuple[str, float, str]:
        text = transaction_text(tx)
        ruled = match_rule(text, compiled)
        if ruled:
            return ruled, 1.0, "rule"
        if model is not None:
            label, confidence = model.predict(text)
            return label, float(confidence), "model"
        return DEFAULT_CATEGORY, 0.0, "fallback"

    return categorize


def ingest_text(
    conn,
    raw_text: str,
    *,
    source: str = "manual",
    received_at: datetime | None = None,
    categorizer: Categorizer | None = None,
) -> IngestResult:
    """Ingest a single notification within the caller's transaction."""
    received_at = received_at or datetime.now()
    raw = RawNotification(source=source, raw_text=raw_text, received_at=received_at)

    raw_id = repo.insert_raw(
        conn,
        source=source,
        received_at=received_at,
        raw_text=raw_text,
        content_hash=raw.content_hash,
    )
    if raw_id is None:
        conn.commit()
        return IngestResult(status="duplicate", detail="notification already ingested")

    tx = parse(raw_text, received_at, source=source)
    if tx is None:
        repo.mark_raw(conn, raw_id, processed=False, error="unparsed")
        repo.log_ingestion(conn, source=source, seen=1, parsed=0, skipped=0, errors=1, note="unparsed")
        conn.commit()
        return IngestResult(status="unparsed", detail="could not extract an amount")

    account_id = repo.get_account_id(conn, tx.account_label)
    merchant_id = repo.get_or_create_merchant(conn, tx.merchant_raw)

    categorize = categorizer or build_categorizer(conn)
    category, confidence, method = categorize(tx)

    cats = repo.category_ids(conn)
    category_id = cats.get(category, cats.get(DEFAULT_CATEGORY))

    tx_id = repo.insert_transaction(
        conn,
        tx=tx,
        account_id=account_id,
        raw_id=raw_id,
        merchant_id=merchant_id,
        category_id=category_id,
        confidence=confidence,
    )
    repo.mark_raw(conn, raw_id, processed=True)
    repo.log_ingestion(conn, source=source, seen=1, parsed=1, skipped=0, errors=0)
    conn.commit()

    return IngestResult(
        status="created" if tx_id else "duplicate",
        transaction_id=tx_id,
        transaction=tx,
        category=category,
        confidence=confidence,
        method=method,
    )


def ingest_many(
    conn,
    items: Iterable[tuple[str, datetime]],
    *,
    source: str = "imap",
    categorizer: Categorizer | None = None,
) -> dict[str, int]:
    """Ingest many ``(raw_text, received_at)`` pairs, building the categorizer once."""
    categorize = categorizer or build_categorizer(conn)
    summary = {"seen": 0, "created": 0, "duplicate": 0, "unparsed": 0}
    for raw_text, received_at in items:
        summary["seen"] += 1
        result = ingest_text(
            conn, raw_text, source=source, received_at=received_at, categorizer=categorize
        )
        summary[result.status] = summary.get(result.status, 0) + 1
    return summary
