<div align="center">

# 💸 Dompet

**A personal finance tracker that reads my own Indonesian bank & e-wallet notifications, auto-categorizes every transaction, and forecasts my end-of-month balance.**

[![CI](https://github.com/azzyth/dompet/actions/workflows/ci.yml/badge.svg)](https://github.com/azzyth/dompet/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Postgres](https://img.shields.io/badge/Postgres-16-336791)

</div>

---

## Why this exists

I check my balance and still have no idea where the money went. Indonesian banks send an
SMS or push notification for **every** transaction — BCA, Mandiri, BNI, BRI, GoPay, OVO,
DANA, ShopeePay — and those messages already contain everything: amount, merchant, time,
channel. Nobody reads them. This project does.

Dompet is a **dogfooding project**: it runs on my real notifications, so the data is
genuine and the pain is real. It is also deliberately built as the "can I *ship* it"
counterweight to my modelling-focused competition repos — a deployed service with a
database, tests, CI, and a dashboard.

## What it does

- **Ingests** transaction notifications over IMAP, a webhook, a CSV e-statement backfill, or a manual paste.
- **Parses** eight Indonesian bank/e-wallet message formats into structured transactions (amount, direction, merchant, channel, timestamp).
- **Auto-categorizes** each transaction with keyword rules and a trained ML classifier, with a confidence score and a review queue for the uncertain ones.
- **Stores** everything in PostgreSQL behind hand-written SQL and reporting views.
- **Forecasts** the end-of-month balance from daily net cashflow (three explicit methods).
- **Alerts** on category drift using a robust z-score against that category's own history.
- **Serves** an API and a dashboard, containerized with Docker.

## Architecture

```
              [ Ingestion adapters ]                     [ Core (pure Python) ]
  IMAP inbox poll ─┐                                    ┌─ parse_sms / parse_email
  E-statement CSV ─┼─► raw_notifications ──► Parser ────┤─ normalize merchant
  Android forward ─┤   (dedupe by hash)                 └─ build Transaction
  manual paste    ─┘                                          │
                                                              v
                                    [ PostgreSQL ]  accounts · transactions · merchants
                                                    categories · category_rules
                                                    ingestion_log · forecasts
                                                              │
                          ┌───────────────────────────────────┼───────────────────────────┐
                          v                                   v                           v
                 [ ML categorizer ]                  [ SQL analytics views ]      [ Forecaster ]
                 rules → TF-IDF models               monthly/category/merchant    daily net cashflow
                 (+ optional IndoBERT)               rollups, burn rate           → end-of-month balance
                          │                                   │                           │
                          └───────────────┬───────────────────┴───────────────┬───────────┘
                                          v                                   v
                                   [ FastAPI ]                         [ Streamlit ]
                          /ingest /transactions /summary            spending chart, trend,
                          /forecast /drift /health                  forecast, drift alerts
```

The design mirrors a pattern I use elsewhere: a **pure-stdlib core** (`dompet.core`,
`dompet.analytics`) that is testable without Postgres or third-party packages, and
**adapters** (`IMAP`, `CSV`, `webhook`, API) behind it. `import dompet.core` works on a
bare Python install.

## Quickstart

### Docker — the whole stack (Postgres + API + dashboard)

```bash
git clone https://github.com/azzyth/dompet && cd dompet
cp .env.example .env
docker compose up --build
```

Schema, seed categories and the reporting views load automatically on first boot.

| Service | URL | What it is |
|---|---|---|
| Dashboard | http://localhost:8501 | Spending, forecast, drift, review queue (Streamlit) |
| API | http://localhost:8000 | HTML landing page in a browser, JSON for clients |
| API docs | http://localhost:8000/docs | Swagger UI |
| Database UI | http://localhost:8080 | Adminer — browse the tables and views |
| Health | http://localhost:8000/health | JSON liveness + DB + model status |

> **Port 5432 is not a web port.** PostgreSQL speaks its own wire protocol there, so
> opening `localhost:5432` in a browser gives `ERR_EMPTY_RESPONSE` by design. Use the
> Database UI (8080) to look at the data.

Then train the categorizer and load a synthetic demo so the dashboard has data.
These run **inside** the container, so nothing extra is needed on the host:

```bash
docker compose exec api python -m dompet.ml.train --config configs/train.yaml
docker compose exec api python scripts/seed_demo.py --n 250 --days 60
docker compose restart api        # pick up the freshly trained model
```

Run the test suite in the container (the DB-backed tests execute here):

```bash
docker compose exec api python -m unittest discover -s tests -v
```

### Local (no Docker)

```bash
pip install -r requirements-dev.txt      # + requirements-dashboard.txt for the UI
cp .env.example .env                     # set DATABASE_URL

python scripts/init_db.py                # schema + seed + views
python scripts/load_rules.py             # keyword rules from dompet/ml/labels.py
python -m dompet.ml.train --config configs/train.yaml   # train the categorizer
python scripts/seed_demo.py --n 250      # optional synthetic data

uvicorn dompet.api.main:app --reload                              # API
streamlit run dompet/dashboard/app.py                            # dashboard
```

## How it works

### 1. Ingestion is idempotent everywhere

Every notification is stored verbatim in `raw_notifications` with a
`UNIQUE content_hash` computed from its normalized text. Re-polling the inbox, re-running
an import, or a retrying webhook can never double-count: the second insert simply conflicts
and is counted as a duplicate. `transactions.raw_id` is `UNIQUE` too, so a transaction
cannot exist twice.

```bash
python scripts/poll_inbox.py       # pull new mail from the configured IMAP folder
curl -X POST localhost:8000/ingest -H 'Content-Type: application/json' \
     -d '{"text":"GoPay: Pembayaran Rp25.000 ke KOPI KENANGAN berhasil"}'
```

### 2. Parsing eight real notification formats

`dompet/core/parsers/` handles BCA, Mandiri, BNI/BRI/CIMB/Permata/Danamon (generic), and
GoPay/OVO/DANA/ShopeePay, with a lenient fallback. The hard parts are number formats
(`Rp50.000` = 50000, `250,000.00` = 250000.00), dates without a year (`24/09`, inferred from
the message date), and not mistaking a **balance** or an **account number** for the
transaction amount. The fixture corpus in `tests/fixtures/notifications/` pins all of it —
add a `.txt` file and a manifest entry and it is tested automatically.

### 3. Categorization: rules first, then the model

`build_categorizer` applies keyword rules, then the ML model, then a safe `Other` default.

Rules are deterministic and catch the high-signal cases the model is weakest on. A concrete
example: the trained model, given the bare string `"GAJI BULANAN"`, predicts *Food & Drink*
(it always saw that phrase with a bank prefix in training). The rule returns *Income*
immediately. The model earns its place on the long tail — novel merchants the rules miss.

Corrections feed back: `POST /transactions/{id}/category` marks a row `is_reviewed`, and the
next `python -m dompet.ml.train --source db` uses those reviewed rows as labels.

### 4. Forecast without a black box

`dompet/analytics/forecast.py` projects the month-end balance from daily net cashflow using
one of three explicit methods:

| method | what it does | when it wins |
|---|---|---|
| `mean` | average daily net over the lookback window | steady spending |
| `median` | same window, median daily net | one big purchase shouldn't skew it |
| `weekday` | per-weekday average net | weekend-heavy spending |

The window **includes zero-spend days**, so a quiet month does not inflate the daily rate.
The response always names the method used.

### 5. Drift detection that isn't fooled once

`dompet/analytics/drift.py` uses a robust z-score (median + MAD) rather than mean/std, so a
single outlier purchase does not permanently widen the "normal" band. When a category has
zero historical spread but differs now, the score saturates at 99 instead of `inf` so alerts
stay JSON-serializable.

## Data model & SQL

`db/schema.sql` defines `accounts`, `raw_notifications`, `merchants`, `categories`,
`category_rules`, `transactions`, `forecasts`, `ingestion_log`.

All reporting reads go through views in `db/views.sql` — no ORM, no query builder, the SQL is
the deliverable:

| view | answers |
|---|---|
| `v_signed_transactions` | debit/credit as signed amounts, joined to merchant + category |
| `v_monthly_category_spend` | spend per category per month |
| `v_merchant_rollup` | where the money actually goes |
| `v_daily_net_cashflow` | daily net / spent / earned — the forecaster's input |
| `v_burn_rate` | trailing 30-day average daily spend, projected to a month |

```sql
SELECT category, SUM(amount) AS total
FROM v_signed_transactions
WHERE direction = 'debit' AND month = date_trunc('month', current_date)::date
GROUP BY category ORDER BY total DESC;
```

## Categorizer results

Trained on a frozen stratified split (`seed: 42`, `test_size: 0.25`), selected by **macro-F1**
— see `reports/metrics_summary.csv` and [`decision_log.md`](./decision_log.md):

| model | accuracy | macro-F1 | note |
|---|---|---|---|
| rules | 0.9545 | 0.9515 | keyword rules (`dompet/ml/labels.py`) |
| logreg | 0.9000 | 0.9008 | word TF-IDF + LogisticRegression |
| linearsvc | 0.9727 | 0.9721 | word+char TF-IDF + calibrated LinearSVC |
| **lightgbm** | **0.9727** | **0.9733** | word TF-IDF + tuned LightGBM |

Honest caveat, also in the decision log: the **synthetic** data is generated from the same
vocabulary the rules were written against, so it *overstates* the rules baseline. On real
statements the model's edge grows, because novel merchants are common. The synthetic numbers
are a wiring smoke test, not a production accuracy claim.

## API

| method | path | purpose |
|---|---|---|
| `GET` | `/health` | DB + model status |
| `POST` | `/ingest` | ingest one notification (`X-Ingest-Token` when `INGEST_TOKEN` is set) |
| `GET` | `/transactions?limit=&unreviewed=` | recent transactions |
| `GET` | `/summary` | balance, burn rate, category + merchant rollups |
| `GET` | `/forecast?method=&lookback_days=` | month-end projection |
| `GET` | `/drift?threshold=` | category drift alerts |
| `POST` | `/transactions/{id}/category` | correct a category (training feedback) |

## Deployment

Nothing here needs a paid tier:

- **Database** — Neon or Supabase free Postgres; set `DATABASE_URL` (add `?sslmode=require`), then run `scripts/init_db.py`.
- **API** — Railway / Render / Fly.io from the included `Dockerfile`; set `DATABASE_URL` and `INGEST_TOKEN`.
- **Dashboard** — Streamlit Community Cloud (main file `dompet/dashboard/app.py`) or Hugging Face Spaces.
- **Ingestion** — run `scripts/poll_inbox.py` on a schedule (cron / Railway cron) against a dedicated inbox.
- **Android forwarder** *(optional)* — a Tasker/Kotlin task POSTs notification text to `/ingest`.

## Privacy

Dompet runs on its owner's own notifications.

- Real statement data is **never committed** — only synthetic/redacted fixtures are.
- Credentials live in `.env` (gitignored); the deployed demo is seeded with `scripts/seed_demo.py`, not real data.
- Account numbers and names are redacted in anything shown publicly.

## Testing

```bash
python -m unittest discover -s tests    # 81 tests; DB + dashboard tests skip without a DB
python -m ruff check dompet tests scripts
```

Tests that need infrastructure skip themselves on a bare install and run where the
dependencies exist:

| Test module | Needs | What it guards |
|---|---|---|
| `test_parsers`, `test_normalize`, … | nothing (stdlib) | parsing, formatting, hashing |
| `test_scripts_runnable` | nothing | `python scripts/*.py` imports the package |
| `test_repository_integration` | Postgres + psycopg | every SQL read path executes |
| `test_dashboard_app` | Streamlit + Postgres | the dashboard app actually renders |

The last one matters because `/_stcore/health` returns `ok` even when the dashboard
script crashes — a health check cannot distinguish a rendered page from a traceback, so
the app is executed instead (Streamlit's own `AppTest` harness):

```bash
docker compose exec dashboard python -m unittest tests.test_dashboard_app -v
```

CI (`.github/workflows/ci.yml`) additionally spins up a Postgres service, loads
schema/seed/views, trains the categorizer, and smoke-tests the API.

## Project layout

```
dompet/
├─ dompet/
│  ├─ core/               # pure stdlib: models, normalize, parsers, rules
│  ├─ analytics/          # pure stdlib: forecast, drift
│  ├─ ml/                 # features, labels, dataset, train, predict, synthetic
│  ├─ adapters/           # imap, csv_import
│  ├─ db/                 # connection, repository (raw SQL)
│  ├─ api/                # FastAPI service
│  └─ dashboard/          # Streamlit app
├─ db/                    # schema.sql, seed.sql, views.sql
├─ configs/train.yaml
├─ scripts/               # init_db, load_rules, poll_inbox, seed_demo
├─ tests/                 # unittest suite + notification fixtures
├─ reports/metrics_summary.csv
└─ decision_log.md
```

## What I'd do next

- Fine-tune **IndoBERT** for the categorizer once real volume justifies it — the frontier step after the TF-IDF baseline.
- Promote manual corrections into `category_rules` automatically, so the rules layer learns with the model.
- Add a weekly WhatsApp/email digest of spending and drift alerts.
- Grow the parser fixture corpus with more bank formats as I collect them.

---

*A personal project, built to practise the whole loop: notification → parse → classify → store → forecast → ship. It runs on my phone's notifications every day.*
