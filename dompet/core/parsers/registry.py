"""Parser registry. Order matters: specific banks win over the generic fallback."""

from __future__ import annotations

import re
from datetime import datetime

from dompet.core.models import Transaction
from dompet.core.parsers import bank_generic, bca, ewallet, mandiri
from dompet.core.parsers.common import parse_notification

PARSERS = [bca, mandiri, ewallet, bank_generic]

# The lenient fallback only fires when the text at least looks like a transaction.
_FALLBACK_HINT = re.compile(
    r"(?i)(?:\bIDR\b|\bRp\.?\s?\d|\b(?:debit|kredit|qris|transfer|pembayaran|trsf|transaksi|tarik)\b)"
)


def detect_source(text: str) -> str | None:
    """Return the parser name that recognizes this text, if any."""
    for parser in PARSERS:
        if parser.detect(text):
            return parser.NAME
    if _FALLBACK_HINT.search(text or ""):
        return "fallback"
    return None


def parse(raw_text: str, received_at: datetime, source: str = "unknown") -> Transaction | None:
    """Parse one notification into a :class:`Transaction`, or ``None`` if unparseable."""
    for parser in PARSERS:
        if not parser.detect(raw_text):
            continue
        tx = parser.parse(raw_text, received_at, source)
        if tx is not None:
            return tx
    if _FALLBACK_HINT.search(raw_text or ""):
        return parse_notification(
            raw_text, received_at, account_label="unknown", source=source
        )
    return None
