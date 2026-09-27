"""Feature text for the categorizer. Pure stdlib."""

from __future__ import annotations

from typing import Any


def transaction_text(tx: Any) -> str:
    """The single field the categorizer reads.

    Built from the merchant plus the raw description so both the clean signal
    ("KOPI KENANGAN") and the noisy one ("PEMBAYARAN ... QRIS") are available.
    """
    parts = [
        getattr(tx, "merchant_raw", None) or "",
        getattr(tx, "description", None) or "",
    ]
    channel = getattr(tx, "channel", None)
    if channel is not None:
        parts.append(getattr(channel, "value", str(channel)))
    return " ".join(p for p in parts if p).strip()


def text_from_row(row: dict) -> str:
    """Build the feature text from a DB row (``description`` + ``merchant`` + ``channel``)."""
    parts = [row.get("merchant") or "", row.get("description") or "", row.get("channel") or ""]
    return " ".join(str(p) for p in parts if p).strip()
