"""E-wallet parser for GoPay / OVO / DANA / ShopeePay.

Formats this targets:
    GoPay: Pembayaran Rp25.000 ke KOPI KENANGAN berhasil. Saldo: Rp75.000
    OVO: Transaksi Rp50.000 di GRAB berhasil
    DANA: Anda melakukan pembayaran Rp30.000 ke WARUNG PAK TOMO
    ShopeePay: Pembayaran Rp15.000 di WARTEG BERHASIL
"""

from __future__ import annotations

import re
from datetime import datetime

from dompet.core.models import Channel, Transaction
from dompet.core.parsers.common import (
    build_transaction,
    detect_direction,
    pick_amount,
)

NAME = "ewallet"

_WALLETS = {
    "GOPAY": "GoPay",
    "OVO": "OVO",
    "DANA": "DANA",
    "SHOPEEPAY": "ShopeePay",
}

_WALLET_RE = re.compile(r"(?:^|\W)(" + "|".join(_WALLETS) + r")(?:\W|$)", re.I)


def detect_wallet(text: str) -> str | None:
    m = _WALLET_RE.search(text or "")
    if not m:
        return None
    return _WALLETS[m.group(1).upper()]


def detect(text: str) -> bool:
    return detect_wallet(text) is not None


def parse(raw_text: str, received_at: datetime, source: str = "unknown") -> Transaction | None:
    wallet = detect_wallet(raw_text)
    if wallet is None:
        return None
    amount = pick_amount(raw_text)
    if amount is None:
        return None
    direction = detect_direction(raw_text)
    tx = build_transaction(
        raw_text=raw_text,
        received_at=received_at,
        amount=amount,
        direction=direction,
        account_label=wallet,
        source=source,
    )
    # E-wallet notifications are always e-wallet channel unless QRIS is explicit.
    channel = Channel.QRIS if tx.channel is Channel.QRIS else Channel.EWALLET
    return Transaction(
        posted_at=tx.posted_at,
        amount=tx.amount,
        direction=tx.direction,
        description=tx.description,
        source=tx.source,
        account_label=tx.account_label,
        channel=channel,
        currency=tx.currency,
        merchant_raw=tx.merchant_raw,
        external_ref=tx.external_ref,
        raw_text=tx.raw_text,
    )
