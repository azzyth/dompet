"""Generic bank parser for BNI / BRI / CIMB / Permata / Danamon / BTN.

These share a shape ("Transaksi Kartu Debit Rp25,000.00 ... di INDOMARET"), so a
single parser with a bank-name lookup covers them all.

Formats this targets:
    BNI: Transaksi Kartu Debit Rp25,000.00 Tgl 24/09/2026 17:01:23 di INDOMARET
    BRI: Transaksi QRIS Rp30.000 tgl 24/09/2026 17:05 di KOPI KENANGAN
"""

from __future__ import annotations

import re
from datetime import datetime

from dompet.core.models import Transaction
from dompet.core.parsers.common import parse_notification

NAME = "bank_generic"

_BANKS = {
    "BNI": "BNI",
    "BRI": "BRI",
    "CIMB": "CIMB",
    "PERMATA": "Permata",
    "DANAMON": "Danamon",
    "BTN": "BTN",
    "MEGA": "Mega",
    "OCBC": "OCBC",
}

_BANK_RE = re.compile(r"(?:^|\W)(" + "|".join(_BANKS) + r")(?:\W|$)", re.I)

# Only treat it as a bank notification if a transaction word is present, so we do
# not swallow an unrelated mention of a bank name.
_TX_WORD = re.compile(r"transaksi|debit|kredit|qris|transfer|pembayaran|tarik", re.I)


def detect_bank(text: str) -> str | None:
    m = _BANK_RE.search(text or "")
    if not m:
        return None
    return _BANKS[m.group(1).upper()]


def detect(text: str) -> bool:
    return detect_bank(text) is not None and bool(_TX_WORD.search(text or ""))


def parse(raw_text: str, received_at: datetime, source: str = "unknown") -> Transaction | None:
    bank = detect_bank(raw_text)
    if bank is None or not _TX_WORD.search(raw_text or ""):
        return None
    return parse_notification(raw_text, received_at, account_label=bank, source=source)
