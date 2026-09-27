"""Synthetic notification generator. Pure stdlib.

Two jobs:
  1. Give the categorizer a labeled dataset to train on *before* there is any real
     data, and give the CI job something deterministic to assert against.
  2. Seed a realistic demo database (`scripts/seed_demo.py`) so the deployed
     dashboard can be shown publicly without exposing real transactions.

Texts mimic real bank / e-wallet formats so the model learns from the same
distribution the parsers produce.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

# category -> (merchant surface forms, merchants, typical rupiah range)
_VOCAB: dict[str, tuple[list[str], list[str], tuple[int, int]]] = {
    "Food & Drink": (
        ["KOPI KENANGAN", "STARBUCKS", "JANJI JIWA", "WARTEG PAK TOMO", "GOFOOD AYAM GEPREK",
         "MCDONALDS", "KFC", "BAKSO PAK KUMIS", "SATE PADANG", "MARTABAK BANGKA", "ES TEH INDONESIA"],
        ["BCA", "Mandiri", "GoPay", "OVO", "DANA", "ShopeePay", "BNI", "BRI"],
        (12_000, 85_000),
    ),
    "Groceries": (
        ["INDOMARET", "ALFAMART", "SUPERINDO", "TRANSMART", "PASAR SAYUR", "TOKO SEMBAKO BU RTI"],
        ["BCA", "Mandiri", "BNI", "BRI", "GoPay", "ShopeePay"],
        (25_000, 320_000),
    ),
    "Transport": (
        ["GOJEK", "GRAB", "PERTAMINA", "PARKIR MALL", "KRL COMMUTER", "TRANSJAKARTA", "DAMRI"],
        ["BCA", "Mandiri", "GoPay", "OVO", "DANA"],
        (4_000, 120_000),
    ),
    "Bills": (
        ["PLN TOKEN LISTRIK", "TELKOMSEL PULSA", "INDIHOME", "BPJS KESEHATAN", "PDAM AIR",
         "TOP UP GOPAY", "KUOTA XL"],
        ["BCA", "Mandiri", "GoPay", "OVO", "DANA", "ShopeePay"],
        (20_000, 500_000),
    ),
    "Health": (
        ["KIMIA FARMA", "APOTEK K24", "KLINIK SEHAT", "GUARDIAN", "WATSONS", "DOKTER GIGI"],
        ["BCA", "Mandiri", "BNI", "GoPay"],
        (30_000, 600_000),
    ),
    "Education": (
        ["GRAMEDIA", "COURSERA", "UDEMY", "SEMINAR DATA", "LES MATEMATIKA", "BUKU KULIAH"],
        ["BCA", "Mandiri", "BNI", "BRI"],
        (50_000, 800_000),
    ),
    "Entertainment": (
        ["NETFLIX", "SPOTIFY", "CGV", "XXI BIOSKOP", "STEAM GAME", "YOUTUBE PREMIUM"],
        ["BCA", "Mandiri", "GoPay", "OVO", "DANA"],
        (15_000, 200_000),
    ),
    "Shopping": (
        ["TOKOPEDIA", "SHOPEE", "LAZADA", "BLIBLI", "UNIQLO", "TIKTOK SHOP", "SOMETHINC"],
        ["BCA", "Mandiri", "GoPay", "ShopeePay", "BNI"],
        (40_000, 1_500_000),
    ),
    "Fees": (
        ["BIAYA ADMIN", "ADMIN FEE", "BIAYA TRANSFER", "DENDA KETERLAMBATAN"],
        ["BCA", "Mandiri", "BNI", "BRI"],
        (2_500, 25_000),
    ),
    "Transfer Out": (
        ["TRANSFER KE BUDI", "TRANSFER KE SARI", "KIRIM UANG IBU", "TRANSFER KE ADIK"],
        ["BCA", "Mandiri", "BNI", "BRI"],
        (50_000, 2_000_000),
    ),
    "Income": (
        ["GAJI BULANAN", "UANG BEASISWA", "HONOR PROYEK", "CASHBACK SHOPEE", "REFUND TOKOPEDIA",
         "TRANSFER MASUK AYAH"],
        ["BCA", "Mandiri", "BNI", "BRI"],
        (100_000, 5_000_000),
    ),
}

_CATEGORIES = list(_VOCAB)


def _rupiah(amount: int) -> str:
    """Format an int as Indonesian rupiah: 250000 -> 'Rp250.000'."""
    return "Rp" + f"{amount:,}".replace(",", ".")


def _notification(category: str, rng: random.Random, when: datetime | None = None) -> str:
    """Build one notification.

    When ``when`` is given, the date and time embedded in the text match it, so the
    parsed ``posted_at`` equals the timestamp the notification actually arrived with.
    Without it the embedded date is random — fine for training text (dates are masked
    out of the features) but wrong for timestamped demo data, where it previously
    produced rows dated in the future.
    """
    surfaces, banks, (lo, hi) = _VOCAB[category]
    merchant = rng.choice(surfaces)
    bank = rng.choice(banks)
    amount = _rupiah(rng.randrange(lo, hi, 500))
    if when is None:
        day, month, year = rng.randint(1, 28), 9, 2026
        time = f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}"
    else:
        day, month, year = when.day, when.month, when.year
        time = f"{when.hour:02d}:{when.minute:02d}:{when.second:02d}"

    if category == "Income":
        return f"{bank}: TRSF E-BANKING CR {day:02d}/{month:02d} {amount} DARI {merchant}"
    if category == "Transfer Out":
        return f"{bank}: TRSF E-BANKING DB {day:02d}/{month:02d} {amount} {merchant}"
    if bank in {"GoPay", "OVO", "DANA", "ShopeePay"}:
        return f"{bank}: Pembayaran {amount} ke {merchant} berhasil"
    if bank == "BCA":
        return f"BCA: TRK {amount} TGL {day:02d}/{month:02d} {time} di {merchant} QRIS"
    return (
        f"{bank}: Transaksi Kartu Debit {amount} "
        f"Tgl {day:02d}/{month:02d}/{year} {time} di {merchant}"
    )


def generate_dataset(n_per_category: int = 40, seed: int = 42) -> list[tuple[str, str]]:
    """Return ``(notification_text, category)`` pairs — balanced across categories."""
    rng = random.Random(seed)
    rows: list[tuple[str, str]] = []
    for category in _CATEGORIES:
        for _ in range(n_per_category):
            rows.append((_notification(category, rng), category))
    rng.shuffle(rows)
    return rows


def generate_notifications(
    n: int = 200, *, days: int = 60, seed: int = 7, end: datetime | None = None
) -> list[tuple[str, datetime]]:
    """Return dated notifications ``(text, received_at)`` for demo seeding.

    The embedded date matches ``received_at``, so seeded rows never land in the future.
    """
    rng = random.Random(seed)
    end = end or datetime.now()
    out: list[tuple[str, datetime]] = []
    for _ in range(n):
        category = rng.choice(_CATEGORIES)
        received = end - timedelta(
            days=rng.randint(0, days), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        out.append((_notification(category, rng, received), received))
    out.sort(key=lambda r: r[1])
    return out
