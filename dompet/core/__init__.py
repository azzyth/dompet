"""Pure-stdlib core: models, normalization, and notification parsing.

Nothing here imports third-party packages, so ``import dompet.core`` works on a
bare Python install and the whole layer is testable without Postgres.
"""

from dompet.core.models import Channel, Direction, RawNotification, Transaction
from dompet.core.normalize import (
    normalize_merchant,
    normalize_text,
    parse_amount,
    parse_datetime,
    raw_hash,
)
from dompet.core.parsers import detect_source, parse

__all__ = [
    "Channel",
    "Direction",
    "RawNotification",
    "Transaction",
    "detect_source",
    "parse",
    "normalize_merchant",
    "normalize_text",
    "parse_amount",
    "parse_datetime",
    "raw_hash",
]
