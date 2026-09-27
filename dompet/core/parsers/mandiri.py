"""Mandiri SMS / e-mail parser.

Formats this targets:
    MANDIRI: Transaksi debit Rp50.000,00 tgl 24-09-2026 17:01:23 di TOKOPEDIA. Saldo Rp1.234.567
    Mandiri: Transfer masuk IDR 1.500.000 dari BUDI SANTOSO tgl 24/09/2026
"""

from __future__ import annotations

import re
from datetime import datetime

from dompet.core.models import Transaction
from dompet.core.parsers.common import parse_notification

NAME = "mandiri"
ACCOUNT = "Mandiri"

_DETECT = re.compile(r"(?:^|\W)MANDIRI(?:\W|$)", re.I)


def detect(text: str) -> bool:
    return bool(_DETECT.search(text or ""))


def parse(raw_text: str, received_at: datetime, source: str = "unknown") -> Transaction | None:
    if not detect(raw_text):
        return None
    return parse_notification(
        raw_text, received_at, account_label=ACCOUNT, source=source
    )
