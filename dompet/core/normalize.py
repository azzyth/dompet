"""Text, amount, and datetime normalization. Pure stdlib, no imports outside it.

Indonesian notifications mix number formats (``Rp50.000`` = 50000) with US-style
ones (``250,000.00``), so :func:`parse_amount` resolves the separator ambiguity
with explicit rules rather than trusting a locale.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

_WS = re.compile(r"\s+")

_MONTHS = {
    "jan": 1, "januari": 1,
    "feb": 2, "februari": 2,
    "mar": 3, "maret": 3,
    "apr": 4, "april": 4,
    "may": 5, "mei": 5,
    "jun": 6, "juni": 6,
    "jul": 7, "juli": 7,
    "aug": 8, "agu": 8, "agus": 8, "agustus": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "okt": 10, "oktober": 10,
    "nov": 11, "november": 11,
    "dec": 12, "des": 12, "desember": 12,
}

_CURRENCY_RE = r"(?:IDR|Rp\.?|RM|USD|SGD|MYR)"

# Everything below is masked out before amount scanning, so a date or time is never
# mistaken for the transaction amount. Guards matter:
#   - dot-separated dates require a 4-digit year, so amounts like `50.000.00` never match;
#   - dot-separated times require a valid hour (0-23) and stand alone (surrounded by
#     whitespace), so `Rp50.000` and bare `5.000` never match;
#   - the slash/dash date alternative is digit-bounded, so reference numbers like a PLN
#     token `1234-5678` are not partially masked.
_DATE_TIME_RE = re.compile(
    r"(?<!\d)\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?(?!\d)"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r"|(?:^|\s)\d{1,2}\.\d{1,2}\.\d{4}(?=\s|$)"
    r"|(?:^|\s)(?:[01]?\d|2[0-3])\.\d{2}(?:\.[0-5]\d)?(?=\s|$)"
)

_MERCHANT_NOISE = re.compile(
    r"\b(?:QRIS|TRSF|E-BANKING|EBANKING|DB|CR|TRK|DEBIT|KREDIT|PORTAL|PEMBAYARAN"
    r"|PEMBELIAN|TRANSAKSI|BERHASIL|SUKSES|TGL|TANGGAL|SALDO|REF|NO|ID|VIA|TUNAI)\b"
)


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def normalize_text(text: str) -> str:
    """Collapse whitespace and apply Unicode NFC.

    NFC matters for the dedupe hash: the same notification can arrive composed
    (``KAFÉ``) through one path and decomposed (``KAFE\u0301``) through another,
    and those must be recognized as the same text or ingestion double-counts.
    """
    return _WS.sub(" ", unicodedata.normalize("NFC", (text or "").strip()))


def normalize_merchant(name: str | None) -> str | None:
    """Collapse a noisy merchant string into a stable canonical form."""
    if not name:
        return None
    s = name.upper()
    s = _MERCHANT_NOISE.sub(" ", s)
    s = re.sub(r"[^0-9A-Z&'. ]+", " ", s)
    s = _WS.sub(" ", s).strip(" .'-")
    return s or None


def mask_datetimes(text: str) -> str:
    """Blank out dates/times so number scanning never mistakes them for amounts."""
    return _DATE_TIME_RE.sub(" ", text)


def raw_hash(raw_text: str) -> str:
    """Identity of a notification from its text alone — the dedupe key for re-polls."""
    return hashlib.sha256(normalize_text(raw_text).upper().encode("utf-8")).hexdigest()


def tx_hash(raw_text: str, posted_at: datetime | None, amount: Decimal | None) -> str:
    payload = "|".join(
        [
            normalize_text(raw_text).upper(),
            posted_at.isoformat() if posted_at else "",
            format(amount, "f") if amount is not None else "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Amounts
# --------------------------------------------------------------------------- #
def parse_amount(token: str | None) -> Decimal | None:
    """Parse a currency-ish token into a :class:`~decimal.Decimal`.

    Handles ``Rp50.000`` -> 50000, ``Rp50.000,00`` -> 50000.00,
    ``250,000.00`` -> 250000.00, ``1.234.567`` -> 1234567, ``20000`` -> 20000.
    """
    if token is None:
        return None
    s = str(token).strip()
    s = re.sub(_CURRENCY_RE, "", s, flags=re.I)
    s = s.replace(" ", "").replace("\u00a0", "")
    s = re.sub(r"[^0-9.,-]", "", s)
    if not s:
        return None
    negative = s.startswith("-")
    s = s.lstrip("-")
    if not s:
        return None

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # The rightmost separator is the decimal point.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", s):
            s = s.replace(",", "")          # 250,000 -> thousands
        elif re.fullmatch(r"\d+,\d{1,2}", s):
            s = s.replace(",", ".")          # 50,00 -> decimal
        else:
            s = s.replace(",", "")
    elif has_dot:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
            s = s.replace(".", "")           # 50.000 -> thousands
        elif re.fullmatch(r"\d+\.\d{1,2}", s):
            pass                              # 15000.50 -> decimal
        else:
            s = s.replace(".", "")

    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


# --------------------------------------------------------------------------- #
# Datetimes
# --------------------------------------------------------------------------- #
def _try_build(year: int, month: int, day: int, hh: int, mm: int, ss: int) -> datetime | None:
    try:
        return datetime(year, month, day, hh, mm, ss)
    except ValueError:
        return None


def _rollback_year(dt: datetime | None, ref: datetime) -> datetime | None:
    """A notification with no year belongs to the reference year unless that puts
    it more than ~6 months in the future (the Dec/Jan boundary)."""
    if dt is not None and dt - ref > timedelta(days=180):
        try:
            return dt.replace(year=dt.year - 1)
        except ValueError:
            return dt
    return dt


def parse_datetime(
    text: str, *, default_year: int | None = None, reference: datetime | None = None
) -> datetime | None:
    ref = reference or datetime.now()
    if default_year is None:
        default_year = ref.year
    t = normalize_text(text)

    # dd/mm/yyyy HH:MM:SS
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", t)
    if m:
        d, mo, y, hh, mm, ss = (int(x) if x else 0 for x in m.groups())
        dt = _try_build(y, mo, d, hh, mm, ss or 0)
        if dt:
            return dt

    # dd/mm/yy HH:MM
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", t)
    if m:
        d, mo, y, hh, mm, ss = (int(x) if x else 0 for x in m.groups())
        year = 2000 + y if y < 70 else 1900 + y
        dt = _try_build(year, mo, d, hh, mm, ss or 0)
        if dt:
            return dt

    # dd Month yyyy [HH:MM[:SS]]
    m = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", t
    )
    if m:
        d = int(m.group(1))
        mo = _MONTHS.get(m.group(2).lower()[:9])
        y = int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mm = int(m.group(5)) if m.group(5) else 0
        ss = int(m.group(6)) if m.group(6) else 0
        if mo:
            dt = _try_build(y, mo, d, hh, mm, ss)
            if dt:
                return dt

    # dd.mm.yyyy [HH.MM[.SS]]  (dot-separated; year must be 4 digits)
    m = re.search(
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+([01]?\d|2[0-3])\.([0-5]\d)(?:\.([0-5]\d))?)?", t
    )
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        ss = int(m.group(6)) if m.group(6) else 0
        dt = _try_build(y, mo, d, hh, mi, ss)
        if dt:
            return dt

    # dd/mm HH.MM[.SS]  (date with a dot-separated time)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})\s+([01]?\d|2[0-3])\.([0-5]\d)(?:\.([0-5]\d))?", t)
    if m:
        d, mo, hh, mi, ss = (int(x) if x else 0 for x in m.groups())
        dt = _try_build(default_year, mo, d, hh, mi, ss or 0)
        return _rollback_year(dt, ref)

    # dd/mm HH:MM[:SS]  (no year -> infer from reference)
    m = re.search(r"(\d{1,2})[/-](\d{1,2})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", t)
    if m:
        d, mo, hh, mm, ss = (int(x) if x else 0 for x in m.groups())
        dt = _try_build(default_year, mo, d, hh, mm, ss or 0)
        return _rollback_year(dt, ref)

    return None
