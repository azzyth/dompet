-- dompet :: schema
-- Idempotent: safe to re-run. Loaded automatically by docker-compose via
-- /docker-entrypoint-initdb.d, or manually with:
--     psql "$DATABASE_URL" -f db/schema.sql

BEGIN;

CREATE TABLE IF NOT EXISTS accounts (
    id         SERIAL PRIMARY KEY,
    label      TEXT NOT NULL UNIQUE,          -- 'BCA', 'GoPay'
    kind       TEXT NOT NULL DEFAULT 'bank'   -- bank | ewallet | cash
               CHECK (kind IN ('bank', 'ewallet', 'cash')),
    currency   TEXT NOT NULL DEFAULT 'IDR',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every inbound notification lands here first, un-parsed. content_hash makes
-- re-polling the same inbox idempotent: identical text is never stored twice.
CREATE TABLE IF NOT EXISTS raw_notifications (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,               -- imap | webhook | csv | manual
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_text     TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    processed    BOOLEAN NOT NULL DEFAULT FALSE,
    parse_error  TEXT
);

CREATE TABLE IF NOT EXISTS merchants (
    id             SERIAL PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    aliases        TEXT[] NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS categories (
    id     SERIAL PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE,
    parent TEXT,
    kind   TEXT NOT NULL DEFAULT 'expense'    -- expense | income | transfer
           CHECK (kind IN ('expense', 'income', 'transfer'))
);

-- Seed keyword rules + rules learned from my own manual corrections.
CREATE TABLE IF NOT EXISTS category_rules (
    id          SERIAL PRIMARY KEY,
    pattern     TEXT NOT NULL,                -- case-insensitive regex
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    priority    INTEGER NOT NULL DEFAULT 100, -- lower wins
    source      TEXT NOT NULL DEFAULT 'seed'  -- seed | learned
);

CREATE TABLE IF NOT EXISTS transactions (
    id           BIGSERIAL PRIMARY KEY,
    account_id   INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    raw_id       BIGINT  REFERENCES raw_notifications(id) ON DELETE SET NULL,
    posted_at    TIMESTAMPTZ NOT NULL,
    amount       NUMERIC(18,2) NOT NULL CHECK (amount > 0),  -- absolute value
    direction    TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
    channel      TEXT NOT NULL DEFAULT 'unknown',
    currency     TEXT NOT NULL DEFAULT 'IDR',
    merchant_id  INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
    description  TEXT,
    category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    confidence   REAL,
    is_reviewed  BOOLEAN NOT NULL DEFAULT FALSE,
    external_ref TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (raw_id)                            -- one transaction per notification
);

CREATE INDEX IF NOT EXISTS idx_tx_posted_at     ON transactions (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tx_category      ON transactions (category_id);
CREATE INDEX IF NOT EXISTS idx_tx_merchant      ON transactions (merchant_id);
CREATE INDEX IF NOT EXISTS idx_tx_account       ON transactions (account_id);
CREATE INDEX IF NOT EXISTS idx_tx_unreviewed    ON transactions (is_reviewed) WHERE NOT is_reviewed;

CREATE TABLE IF NOT EXISTS forecasts (
    id               BIGSERIAL PRIMARY KEY,
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    horizon_day      DATE NOT NULL,
    predicted_balance NUMERIC(18,2) NOT NULL,
    model_version    TEXT NOT NULL DEFAULT 'v0'
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id         BIGSERIAL PRIMARY KEY,
    source     TEXT NOT NULL,
    run_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_seen     INTEGER NOT NULL DEFAULT 0,
    n_parsed   INTEGER NOT NULL DEFAULT 0,
    n_skipped  INTEGER NOT NULL DEFAULT 0,
    n_errors   INTEGER NOT NULL DEFAULT 0,
    note       TEXT
);

COMMIT;
