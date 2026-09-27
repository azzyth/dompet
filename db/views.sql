-- dompet :: reporting views
-- These are the "SQL proof": every number the API and dashboard show comes from
-- here, so the analytics logic is auditable SQL rather than hidden in Python.
--
-- Load with:  psql "$DATABASE_URL" -f db/views.sql

-- Signed amount helper: debit is negative, credit positive.
CREATE OR REPLACE VIEW v_signed_transactions AS
SELECT
    t.id,
    t.posted_at,
    t.posted_at::date                                        AS day,
    date_trunc('month', t.posted_at)::date                   AS month,
    t.direction,
    t.channel,
    c.name                                                   AS category,
    COALESCE(m.canonical_name, NULLIF(t.description, ''), 'UNKNOWN') AS merchant,
    t.description,
    t.amount,
    CASE WHEN t.direction = 'credit' THEN t.amount ELSE -t.amount END AS signed_amount,
    t.confidence,
    t.is_reviewed
FROM transactions t
LEFT JOIN categories c ON c.id = t.category_id
LEFT JOIN merchants  m ON m.id = t.merchant_id;

-- Monthly spend per category.
CREATE OR REPLACE VIEW v_monthly_category_spend AS
SELECT
    month,
    category,
    SUM(amount)  AS total,
    COUNT(*)     AS n_tx,
    ROUND(AVG(amount), 2) AS avg_tx
FROM v_signed_transactions
WHERE direction = 'debit'
GROUP BY month, category
ORDER BY month DESC, total DESC;

-- Merchant rollup — where the money actually goes.
CREATE OR REPLACE VIEW v_merchant_rollup AS
SELECT
    merchant,
    category,
    SUM(amount)   AS total,
    COUNT(*)      AS n_tx,
    MAX(day)      AS last_seen
FROM v_signed_transactions
WHERE direction = 'debit'
GROUP BY merchant, category
ORDER BY total DESC;

-- Daily net cashflow — the input the forecaster models.
CREATE OR REPLACE VIEW v_daily_net_cashflow AS
SELECT
    day,
    SUM(signed_amount)                                            AS net,
    SUM(CASE WHEN direction = 'debit'  THEN amount ELSE 0 END)    AS spent,
    SUM(CASE WHEN direction = 'credit' THEN amount ELSE 0 END)    AS earned,
    COUNT(*)                                                      AS n_tx
FROM v_signed_transactions
GROUP BY day
ORDER BY day;

-- Where the rows came from (imap / csv / webhook / manual / demo). Used by the
-- dashboard to label synthetic demo data honestly without guessing from volume.
CREATE OR REPLACE VIEW v_source_mix AS
SELECT
    COALESCE(rn.source, 'unknown') AS source,
    COUNT(*)                       AS n_tx,
    MIN(t.posted_at)::date         AS first_seen,
    MAX(t.posted_at)::date         AS last_seen
FROM transactions t
LEFT JOIN raw_notifications rn ON rn.id = t.raw_id
GROUP BY 1
ORDER BY n_tx DESC;

-- Burn rate: spend over the trailing 30 calendar days, projected to a month.
-- The denominator is the 30-day calendar window (quiet days count as zero spend),
-- matching the forecaster's basis — averaging only over days *with* spend would
-- overstate the daily rate for anyone whose spending is sporadic.
CREATE OR REPLACE VIEW v_burn_rate AS
SELECT
    ROUND(COALESCE(SUM(daily_spend), 0) / 30.0, 2)  AS avg_daily_spend,
    ROUND(COALESCE(SUM(daily_spend), 0), 2)        AS projected_monthly_spend,
    COUNT(*)                                        AS days_with_spend,
    30                                              AS days_observed
FROM (
    SELECT t.posted_at::date AS day, SUM(t.amount) AS daily_spend
    FROM v_signed_transactions t
    WHERE t.direction = 'debit'
      AND t.posted_at::date >= current_date - 29
      AND t.posted_at::date <= current_date   -- never count future-dated rows
    GROUP BY 1
) s;
