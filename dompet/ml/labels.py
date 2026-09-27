"""Seed keyword rules — the single source of truth for rule-based categorization.

`scripts/load_rules.py` loads these into the `category_rules` table, and runtime
categorization falls back to them when the table is empty. Keeping them here (not
duplicated in SQL) means the rules are testable and version-controlled in one place.
"""

from __future__ import annotations

from dompet.core.rules import Rule, compile_rules, match_rule

SEED_RULES: list[Rule] = [
    Rule(r"(?i)kopi|coffee|kenangan|starbucks|janji jiwa|tomoro|kulo|es teh", "Food & Drink", 10),
    Rule(
        r"(?i)warteg|warung|\bnasi\b|\bayam\b|bakso|\bmie\b|\bsate\b|padang|\bmakan\b|resto|kfc|mcd|"
        r"burger|pizza|gofood|grabfood|shopeefood|geprek|martabak|soto|\bbubur\b",
        "Food & Drink",
        20,
    ),
    Rule(
        r"(?i)indomaret|alfamart|superindo|hypermart|transmart|ranch market|grocer|sayur|pasar|toko sembako",
        "Groceries",
        30,
    ),
    Rule(
        r"(?i)gojek|grab|ojek|taksi|taxi|krl|mrt|lrt|transjakarta|\bbus\b|damri|bensin|"
        r"pertamina|shell|parkir|\btol\b|flazz|e-?toll",
        "Transport",
        30,
    ),
    # Bills: the *reason* for the payment (a top-up or a utility), never the wallet
    # itself. Matching bare `gopay|ovo|dana|shopeepay` used to catch every e-wallet
    # notification, because the provider name is in the text of all of them — so any
    # e-wallet payment to a merchant no other rule knew was mislabeled "Bills"
    # instead of falling through to the model.
    Rule(
        r"(?i)\btop.?up\b|\btopup\b|\bisi ulang\b|pengisian saldo|"
        r"pulsa|kuota|telkomsel|indosat|\btri\b|\bxl\b|pln|token listrik|listrik|"
        r"\bair\b|pdam|internet|indihome|wifi|bpjs|asuransi",
        "Bills",
        40,
    ),
    Rule(r"(?i)apotek|klinik|rumah sakit|dokter|gigi|vitamin|kimia farma|guardian|watsons", "Health", 35),
    Rule(
        r"(?i)\bbuku\b|gramedia|course|coursera|udemy|seminar|\bles\b|tutor|kuliah|\bspp\b|\bukt\b",
        "Education",
        35,
    ),
    Rule(
        r"(?i)bioskop|cinema|cgv|xxi|netflix|spotify|steam|game|top ?up game|youtube premium|viu",
        "Entertainment",
        35,
    ),
    Rule(
        r"(?i)shopee(?!pay)|tokopedia|lazada|blibli|tiktok shop|uniqlo|h&m|zara|\bmall\b|"
        r"skincare|wardah|somethinc",
        "Shopping",
        35,
    ),
    Rule(r"(?i)trsf|transfer|kirim uang|outgoing|ke rekening", "Transfer Out", 60),
    Rule(r"(?i)biaya admin|admin fee|\bfee\b|denda|materai|pajak", "Fees", 15),
    # Income: word-bounded stems only. Bare "bunga" and "terima" caused false
    # positives (flower shops, "terima kasih"), so they now need explicit context.
    Rule(
        r"(?i)\b(gaji|payroll|salary|upah|honor|beasiswa|refund|cashback|dividen)\b"
        r"|\btransfer masuk\b|\bdana masuk\b|\buang masuk\b|\bditerima\b|\bmenerima\b"
        r"|\bsetor(?:an)?\b|\bbunga (?:bank|tabungan|deposito)\b",
        "Income",
        10,
    ),
]

COMPILED_SEED_RULES = compile_rules(SEED_RULES)


def label_text(text: str) -> str:
    """Rule-based category for a text, defaulting to ``Other``."""
    return match_rule(text, COMPILED_SEED_RULES) or "Other"
