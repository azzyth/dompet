"""Amount / datetime / merchant normalization."""

from __future__ import annotations

import unittest
from datetime import datetime
from decimal import Decimal

from dompet.core.normalize import (
    mask_datetimes,
    normalize_merchant,
    normalize_text,
    parse_amount,
    parse_datetime,
    raw_hash,
    tx_hash,
)


class ParseAmountTest(unittest.TestCase):
    def test_indonesian_thousands(self):
        self.assertEqual(parse_amount("Rp50.000"), Decimal("50000"))
        self.assertEqual(parse_amount("IDR 1.234.567"), Decimal("1234567"))
        self.assertEqual(parse_amount("Rp1.234.567"), Decimal("1234567"))

    def test_indonesian_decimal_comma(self):
        self.assertEqual(parse_amount("Rp50.000,00"), Decimal("50000.00"))
        self.assertEqual(parse_amount("1.500.000,00"), Decimal("1500000.00"))

    def test_us_style(self):
        self.assertEqual(parse_amount("250,000.00"), Decimal("250000.00"))
        self.assertEqual(parse_amount("25,000.00"), Decimal("25000.00"))

    def test_plain_and_decimal_point(self):
        self.assertEqual(parse_amount("20000"), Decimal("20000"))
        self.assertEqual(parse_amount("15000.50"), Decimal("15000.50"))

    def test_currency_words_and_negative(self):
        self.assertEqual(parse_amount("RM250,000.00"), Decimal("250000.00"))
        self.assertEqual(parse_amount("-5000"), Decimal("-5000"))

    def test_garbage(self):
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("Rp"))
        self.assertIsNone(parse_amount("abc"))


class MaskDatetimeTest(unittest.TestCase):
    def test_masks_dates_and_times(self):
        masked = mask_datetimes("TRK 50000 TGL 24/09 17:01:23 di TOKO")
        self.assertNotIn("24/09", masked)
        self.assertNotIn("17:01", masked)
        self.assertIn("50000", masked)

    def test_masks_full_date(self):
        masked = mask_datetimes("tgl 24-09-2026 17:01:23 di X")
        self.assertNotIn("2026", masked)


class ParseDatetimeTest(unittest.TestCase):
    def setUp(self):
        self.ref = datetime(2026, 9, 24, 18, 0, 0)

    def test_full_dmy(self):
        self.assertEqual(
            parse_datetime("tgl 24-09-2026 17:01:23", reference=self.ref),
            datetime(2026, 9, 24, 17, 1, 23),
        )

    def test_day_month_only_infers_year(self):
        self.assertEqual(
            parse_datetime("TGL 24/09 17:01:23", reference=self.ref),
            datetime(2026, 9, 24, 17, 1, 23),
        )

    def test_month_rolls_back_across_new_year(self):
        # A 31/12 notification seen on 2/1 belongs to the previous year.
        ref = datetime(2027, 1, 2, 10, 0, 0)
        self.assertEqual(
            parse_datetime("tgl 31/12 23:30", reference=ref),
            datetime(2026, 12, 31, 23, 30),
        )

    def test_month_name(self):
        self.assertEqual(
            parse_datetime("24 Sep 2026 17:05", reference=self.ref),
            datetime(2026, 9, 24, 17, 5, 0),
        )

    def test_none_when_absent(self):
        self.assertIsNone(parse_datetime("no date here", reference=self.ref))


class NormalizeMerchantTest(unittest.TestCase):
    def test_strips_noise_tokens(self):
        self.assertEqual(normalize_merchant("TOKOPEDIA QRIS"), "TOKOPEDIA")
        self.assertEqual(normalize_merchant("PEMBAYARAN KOPI KENANGAN"), "KOPI KENANGAN")

    def test_none_for_blank(self):
        self.assertIsNone(normalize_merchant(""))
        self.assertIsNone(normalize_merchant("  QRIS  "))


class HashTest(unittest.TestCase):
    def test_raw_hash_is_whitespace_insensitive(self):
        self.assertEqual(raw_hash("BCA: TRK 50000"), raw_hash("BCA:  TRK\n50000 "))

    def test_raw_hash_differs_on_content(self):
        self.assertNotEqual(raw_hash("BCA: TRK 50000"), raw_hash("BCA: TRK 50001"))

    def test_tx_hash_depends_on_time_and_amount(self):
        a = tx_hash("x", datetime(2026, 9, 24), Decimal("50000"))
        b = tx_hash("x", datetime(2026, 9, 24), Decimal("50001"))
        self.assertNotEqual(a, b)


class NormalizeTextTest(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(normalize_text("  a   b \n c "), "a b c")


class UnicodeNormalizationTest(unittest.TestCase):
    """Regression: NFD-composed text must hash identically to NFC, or the same
    notification arriving through two ingestion paths double-counts."""

    def test_nfc_folds_combining_characters(self):
        self.assertEqual(normalize_text("KAFE\u0301 UNTUNG"), normalize_text("KAF\u00c9 UNTUNG"))

    def test_raw_hash_is_unicode_form_insensitive(self):
        self.assertEqual(
            raw_hash("bayar Rp25.000 di KAFE\u0301"), raw_hash("bayar Rp25.000 di KAF\u00c9")
        )

    def test_nonbreaking_space_is_whitespace(self):
        self.assertEqual(normalize_text("a\u00a0b"), "a b")
        self.assertEqual(raw_hash("BCA:\u00a0TRK 50000"), raw_hash("BCA: TRK  50000"))


class MaskDottedDatetimeTest(unittest.TestCase):
    """Regression: dot-separated dates/times must be masked so a bare amount is
    never read as the date (e.g. `TGL 24.09.2026 TRK 50000` -> amount 24,092,026)."""

    def test_masks_dotted_date(self):
        masked = mask_datetimes("TGL 24.09.2026 TRK 50000")
        self.assertNotIn("24.09.2026", masked)
        self.assertIn("50000", masked)

    def test_masks_dotted_datetime(self):
        masked = mask_datetimes("BNI: 24.09.2026 17.01 Transaksi 25000")
        self.assertNotIn("24.09.2026", masked)
        self.assertNotIn("17.01", masked)
        self.assertIn("25000", masked)

    def test_masks_dotted_time_with_seconds(self):
        self.assertNotIn("17.01", mask_datetimes("pukul 17.01.23 selesai"))

    def test_never_masks_amounts(self):
        for amount in ("Rp50.000", "Rp1.234.567", "50.000", "250000.00", "1.500.000,00",
                       "50.000.00", "5.000", "15000.50"):
            self.assertIn(amount, mask_datetimes(f"TRK {amount} di X"), amount)

    def test_reference_numbers_are_not_partially_masked(self):
        # A PLN token like 1234-5678 must not have "34-56" blanked out.
        masked = mask_datetimes("token 1234-5678-9012-3456-7890 sukses")
        self.assertIn("1234-5678", masked)


class ParseDottedDatetimeTest(unittest.TestCase):
    def setUp(self):
        self.ref = datetime(2026, 9, 24, 18, 0, 0)

    def test_dotted_date_with_dotted_time(self):
        self.assertEqual(
            parse_datetime("tgl 24.09.2026 17.01.23", reference=self.ref),
            datetime(2026, 9, 24, 17, 1, 23),
        )

    def test_dotted_date_only(self):
        self.assertEqual(
            parse_datetime("tgl 24.09.2026", reference=self.ref), datetime(2026, 9, 24)
        )

    def test_slash_date_with_dotted_time(self):
        self.assertEqual(
            parse_datetime("tgl 24/09 17.05", reference=self.ref),
            datetime(2026, 9, 24, 17, 5, 0),
        )

    def test_amount_is_not_parsed_as_datetime(self):
        self.assertIsNone(parse_datetime("TRK Rp50.000 di X", reference=self.ref))


if __name__ == "__main__":
    unittest.main()
