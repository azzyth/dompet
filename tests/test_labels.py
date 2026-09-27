"""Keyword rules: expected categories, priorities, and regression guards.

The regression tests pin two collisions that were fixed: "bunga" (interest) vs
"bunga" (flower), and the unbounded "mie" matching inside names like "JAMIE".
"""

from __future__ import annotations

import unittest

from dompet.ml.labels import label_text


class LabelTextTest(unittest.TestCase):
    def test_expected_categories(self):
        cases = {
            "KOPI KENANGAN": "Food & Drink",
            "NASI PADANG": "Food & Drink",
            "INDOMARET": "Groceries",
            "GOJEK": "Transport",
            "TOKOPEDIA": "Shopping",
            "NETFLIX": "Entertainment",
            "BIAYA ADMIN": "Fees",
            "GAJI BULANAN": "Income",
            "TRANSFER KE BUDI": "Transfer Out",
            "APOTEK K24": "Health",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(label_text(text), expected)

    def test_unknown_text_is_other(self):
        self.assertEqual(label_text(""), "Other")
        self.assertEqual(label_text("QWERTY ZXCV"), "Other")

    def test_bunga_interest_vs_flower(self):
        # "bunga bank" is income (interest); a flower shop is not.
        self.assertEqual(label_text("BUNGA BANK"), "Income")
        self.assertNotEqual(label_text("TOKO BUNGA MEKAR"), "Income")

    def test_terima_kasih_is_not_income(self):
        self.assertNotEqual(label_text("TERIMA KASIH"), "Income")

    def test_mie_does_not_match_inside_names(self):
        self.assertNotEqual(label_text("JAMIE"), "Food & Drink")

    def test_priority_income_beats_transfer(self):
        # A credit notification mentions both a transfer token and "gaji";
        # the higher-priority income rule must win.
        self.assertEqual(label_text("TRSF E-BANKING CR GAJI BULANAN"), "Income")

    def test_wallet_name_does_not_hijack_the_category(self):
        """Regression: every e-wallet notification contains the provider name
        ("GoPay:", "OVO:"), so matching bare wallet names forced those rows to Bills
        and denied the model a chance on merchants the rules don't know."""
        self.assertEqual(
            label_text("GoPay: Pembayaran Rp45.000 ke TOKO ELEKTRONIK JAYA berhasil"), "Other"
        )
        self.assertNotEqual(label_text("OVO: Transaksi Rp50.000 di GRAB berhasil"), "Bills")

    def test_top_ups_and_utilities_are_still_bills(self):
        self.assertEqual(label_text("GoPay: Top up Rp100.000 berhasil"), "Bills")
        self.assertEqual(label_text("DANA: Pengisian saldo Rp50.000 berhasil"), "Bills")
        self.assertEqual(label_text("PLN TOKEN LISTRIK"), "Bills")
        self.assertEqual(label_text("TELKOMSEL PULSA"), "Bills")
        self.assertEqual(label_text("BPJS KESEHATAN"), "Bills")


if __name__ == "__main__":
    unittest.main()
