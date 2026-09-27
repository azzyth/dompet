-- dompet :: seed data
-- Categories and accounts only. The keyword rules live in ONE place —
-- `dompet/ml/labels.py:SEED_RULES` — and are loaded by `scripts/load_rules.py`
-- so they are never duplicated between SQL and Python.

BEGIN;

INSERT INTO categories (name, parent, kind) VALUES
    ('Food & Drink',  NULL,           'expense'),
    ('Groceries',     NULL,           'expense'),
    ('Transport',     NULL,           'expense'),
    ('Bills',         NULL,           'expense'),
    ('Top-up',        NULL,           'expense'),
    ('Health',        NULL,           'expense'),
    ('Education',     NULL,           'expense'),
    ('Entertainment', NULL,           'expense'),
    ('Shopping',      NULL,           'expense'),
    ('Transfer Out',  NULL,           'transfer'),
    ('Fees',          NULL,           'expense'),
    ('Income',        NULL,           'income'),
    ('Other',         NULL,           'expense')
ON CONFLICT (name) DO NOTHING;

INSERT INTO accounts (label, kind) VALUES
    ('BCA', 'bank'), ('Mandiri', 'bank'), ('BNI', 'bank'), ('BRI', 'bank'),
    ('GoPay', 'ewallet'), ('OVO', 'ewallet'), ('DANA', 'ewallet'), ('ShopeePay', 'ewallet'),
    ('Cash', 'cash')
ON CONFLICT (label) DO NOTHING;

COMMIT;
