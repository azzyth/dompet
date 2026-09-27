"""BCA SMS / e-mail parser.

Formats this targets (all real BCA notification shapes):
    BCA: TRK 50000 TGL 24/09 17:01:23 di TOKOPEDIA QRIS
    BCA: TRSF E-BANKING DB 24/09 250000.00 KE 1234567890 BUDI SANTOSO
    BCA: TRSF E-BANKING CR 24/09 1.500.000,00 DARI BUDI SANTOSO
"""

from __future__ import annotations

import re
from datetime import datetime

from dompet.core.models import Transaction
from dompet.core.parsers.common import parse_notification

NAME = "bca"
ACCOUNT = "BCA"

_DETECT = re.compile(r"(?:^|\W)BCA(?:\W|$)", re.I)


def detect(text: str) -> bool:
    return bool(_DETECT.search(text or ""))


def parse(raw_text: str, received_at: datetime, source: str = "unknown") -> Transaction | None:
    if not detect(raw_text):
        return None
    return parse_notification(
        raw_text, received_at, account_label=ACCOUNT, source=source
    )
