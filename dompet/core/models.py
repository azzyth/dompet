"""Domain models for parsed transactions. Pure stdlib."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from dompet.core.normalize import raw_hash, tx_hash


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class Channel(StrEnum):
    QRIS = "qris"
    TRANSFER = "transfer"
    CARD = "card"
    ATM = "atm"
    EWALLET = "ewallet"
    CASH = "cash"
    FEE = "fee"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RawNotification:
    """An inbound notification before parsing (kept verbatim for auditability)."""

    source: str
    raw_text: str
    received_at: datetime

    @property
    def content_hash(self) -> str:
        return raw_hash(self.raw_text)


@dataclass(frozen=True)
class Transaction:
    """A parsed, normalized transaction.

    ``amount`` is always the absolute value; ``signed_amount`` applies the
    direction (debit negative, credit positive) for cashflow math.
    """

    posted_at: datetime
    amount: Decimal
    direction: Direction
    description: str
    source: str = "unknown"
    account_label: str = "unknown"
    channel: Channel = Channel.UNKNOWN
    currency: str = "IDR"
    merchant_raw: str | None = None
    external_ref: str | None = None
    raw_text: str = ""

    @property
    def signed_amount(self) -> Decimal:
        return -self.amount if self.direction is Direction.DEBIT else self.amount

    @property
    def content_hash(self) -> str:
        return tx_hash(self.raw_text, self.posted_at, self.amount)

    @property
    def is_expense(self) -> bool:
        return self.direction is Direction.DEBIT
