"""Shared extraction logic used by every bank / e-wallet parser. Pure stdlib."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from dompet.core.models import Channel, Direction, Transaction
from dompet.core.normalize import (
    mask_datetimes,
    normalize_merchant,
    normalize_text,
    parse_amount,
    parse_datetime,
)

CURRENCY = r"(?:IDR|Rp\.?|RM|USD|SGD|MYR)"

# A number preceded by one of these is a balance / account number, not the amount.
_EXCLUDE_PREFIX = ("SALDO", "BALANCE", "REF", "NO.", "NAMA", "REK", " KE ", "BUKU")

_NUMBER_RE = re.compile(rf"(?P<cur>{CURRENCY})?\s*(?P<num>\d[\d.,]*\d|\d)")

_CREDIT_WORDS = re.compile(
    r"\b(masuk|diterima|terima|menerima|mendapat|mendapatkan|gaji|salary|payroll"
    r"|honor|beasiswa|refund|cashback|dividen|bunga|deposit|setor)\b"
)
_DEBIT_WORDS = re.compile(
    r"\b(pembayaran|pembelian|penarikan|tarik|bayar|purchase|transfer ke|"
    r"kirim uang|outgoing|debit)\b"
)


def detect_direction(text: str) -> Direction:
    tokens = set(re.findall(r"[A-Z]+", " " + normalize_text(text).upper() + " "))
    if tokens & {"CR", "KR", "KREDIT"}:
        return Direction.CREDIT
    if tokens & {"DB", "DEBIT", "TRK"}:
        return Direction.DEBIT
    t = normalize_text(text)
    if _CREDIT_WORDS.search(t):
        return Direction.CREDIT
    if _DEBIT_WORDS.search(t):
        return Direction.DEBIT
    return Direction.DEBIT  # notifications are overwhelmingly outgoing


def detect_channel(text: str) -> Channel:
    t = normalize_text(text).upper()
    if "QRIS" in t:
        return Channel.QRIS
    if re.search(r"\bTRSF\b|E-?BANKING|TRANSFER|KIRIM UANG|OUTGOING", t):
        return Channel.TRANSFER
    if re.search(r"KARTU|CARD|VISA|MASTERCARD|DEBIT CARD", t):
        return Channel.CARD
    if re.search(r"\bATM\b|TARIK TUNAI|PENARIKAN", t):
        return Channel.ATM
    if re.search(r"GOPAY|OVO|DANA|SHOPEEPAY|E-?WALLET", t):
        return Channel.EWALLET
    if re.search(r"BIAYA|ADMIN|\bFEE\b", t):
        return Channel.FEE
    return Channel.UNKNOWN


def amount_candidates(text: str) -> list[dict]:
    masked = mask_datetimes(normalize_text(text))
    out: list[dict] = []
    for m in _NUMBER_RE.finditer(masked):
        value = parse_amount(m.group("num"))
        if value is None or value <= 0:
            continue
        prefix = masked[max(0, m.start() - 14) : m.start()].upper()
        out.append(
            {
                "value": value,
                "currency": bool(m.group("cur")),
                "excluded": any(k in prefix for k in _EXCLUDE_PREFIX),
                "digits": len(re.sub(r"\D", "", m.group("num"))),
                "pos": m.start(),
            }
        )
    return out


def pick_amount(text: str) -> Decimal | None:
    """Best-effort transaction amount.

    Prefer a currency-prefixed number ("Rp50.000"); otherwise the first bare
    number with at least three digits that is not a balance or an account number.
    """
    candidates = amount_candidates(text)
    strong = [c for c in candidates if c["currency"] and not c["excluded"]]
    if strong:
        return strong[0]["value"]
    soft = [c for c in candidates if not c["excluded"] and c["digits"] >= 3]
    if soft:
        return soft[0]["value"]
    return None


def extract_merchant(text: str) -> str | None:
    t = normalize_text(mask_datetimes(text))
    patterns = [
        r"\b(?:di|ke|kepada|merchant|at)\s+([A-Za-z][A-Za-z0-9&'.\- ]{2,40})",
        r"\b(?:ke|kepada)\s+\d+\s+([A-Za-z][A-Za-z0-9&'.\- ]{2,40})",
    ]
    for pat in patterns:
        m = re.search(pat, t, re.I)
        if not m:
            continue
        name = re.split(
            r"\b(?:berhasil|sukses|saldo|tgl|tanggal|pada|sebesar|dengan|ref|no|buku)\b",
            m.group(1),
            flags=re.I,
        )[0]
        cleaned = normalize_merchant(name)
        if cleaned:
            return cleaned
    return None


def build_description(text: str, merchant: str | None) -> str:
    base = normalize_text(mask_datetimes(text))
    base = re.sub(r"\s+", " ", base).strip()
    return base[:280]


def build_transaction(
    *,
    raw_text: str,
    received_at: datetime,
    amount: Decimal,
    direction: Direction,
    account_label: str,
    source: str,
) -> Transaction:
    merchant = extract_merchant(raw_text)
    posted_at = parse_datetime(raw_text, reference=received_at) or received_at
    return Transaction(
        posted_at=posted_at,
        amount=amount,
        direction=direction,
        description=build_description(raw_text, merchant),
        source=source,
        account_label=account_label,
        channel=detect_channel(raw_text),
        merchant_raw=merchant,
        raw_text=raw_text,
    )


def parse_notification(
    raw_text: str,
    received_at: datetime,
    *,
    account_label: str = "unknown",
    source: str = "unknown",
) -> Transaction | None:
    """Generic: parse any notification that carries a recognizable amount."""
    amount = pick_amount(raw_text)
    if amount is None:
        return None
    return build_transaction(
        raw_text=raw_text,
        received_at=received_at,
        amount=amount,
        direction=detect_direction(raw_text),
        account_label=account_label,
        source=source,
    )
