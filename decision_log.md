# Decision log — Dompet

Records the non-obvious choices, and the evidence behind them. Same discipline as my
competition repos: decide on a frozen split, write down why, move on.

---

## 1. Why rules run before the model

`dompet/ingest.py:build_categorizer` applies keyword rules first, then the ML model,
then a safe `Other` default.

Reason: rules are deterministic, explainable, and free, and they resolve the cases the
model is weakest on. A concrete example — the trained model, asked to classify the bare
string `"GAJI BULANAN"`, returns **Food & Drink** (0.97), because in the synthetic
training data an income notification always carried a bank/channel prefix. The rule set
returns **Income** immediately. Rules catch the high-signal cases; the model handles the
long tail of novel merchants the rules miss.

Corrections flow back: a manual recategorization sets `is_reviewed = true`, and the next
training run (`--source db`) uses those reviewed rows as labels — the active-learning loop.

## 2. Why TF-IDF, not embeddings (yet)

The categorizer is a text classifier over short merchant strings. On a few hundred rows,
sparse TF-IDF n-grams are strong, fast, and entirely interpretable, and they are the
correct baseline before reaching for a transformer. Embeddings/fine-tuned IndoBERT are
the natural next step **once there is real data volume** — on synthetic data they would
overfit and prove nothing. Keeping the baseline honest is the point.

## 3. Model selection — frozen stratified split

`configs/train.yaml` fixes `seed: 42` and `test_size: 0.25`; the split is stratified so
every category appears in test. The winner is chosen by **macro-F1** (not accuracy),
because categories are the thing that matters and class balance is not guaranteed once
real data arrives.

Latest run (`python -m dompet.ml.train --config configs/train.yaml`, synthetic, 440 rows,
11 categories) → `reports/metrics_summary.csv`:

| model | accuracy | macro-F1 | note |
|---|---|---|---|
| rules | 0.9545 | 0.9515 | keyword rules from `dompet/ml/labels.py` |
| logreg | 0.9000 | 0.9008 | word 1–2 gram TF-IDF + LogisticRegression |
| linearsvc | 0.9727 | 0.9721 | word+char TF-IDF + calibrated LinearSVC |
| lightgbm | 0.9727 | **0.9733** | word TF-IDF + tuned LightGBM |

Selected: **lightgbm** (delta vs rules **+0.0218** macro-F1).

## 4. LightGBM was badly tuned at first — recorded because it is instructive

The first LightGBM configuration used the library defaults
(`num_leaves=31`, `min_child_samples=20`) and scored **0.40** macro-F1 — worse than the
rules baseline, on a task where it should be competitive. The cause was overfitting on
sparse, high-dimensional TF-IDF features with only ~330 training rows. A shallow,
regularized configuration fixed it:

```python
LGBMClassifier(
    n_estimators=600, learning_rate=0.05, num_leaves=7,
    min_child_samples=2, colsample_bytree=0.6, subsample=0.9, subsample_freq=1,
)
```

macro-F1 0.40 → **0.9733**. The lesson: a model that looks "broken" is usually a
hyperparameter problem on small data, and the way to tell is to sweep a couple of
sensible configurations rather than abandon or ship it untuned.

## 5. Synthetic data overstates the rules baseline

`lightgbm` beats `rules` by only ~0.02 here, and that gap is **flattered by the setup**:
the synthetic notifications are generated from the *same* merchant vocabulary the rules
were written against, so the rules rarely miss. On real statements, novel merchants
("TOKO BUNGA MEKAR", "NASI UDUK MBAH SOM") are common and the rules fall off — that is
where the model's advantage actually grows. The synthetic numbers are a smoke test that
the pipeline is wired correctly, not a claim about production accuracy.

## 6. Two rule collisions fixed (regression-tested)

Discovered while spot-checking the combined categorizer:

- `bunga` (bank interest → Income) matched **"TOKO BUNGA MEKAR"** (flower shop). Fixed by
  requiring context: `bunga (bank|tabungan|deposito)`.
- Unbounded `mie` matched inside **"JAMIE"**. Fixed with word boundaries (`\bmie\b`) on
  the short, collision-prone tokens (`nasi`, `ayam`, `mie`, `sate`, `buku`, `mall`, …).
- Bare `terima` matched **"TERIMA KASIH"**. Replaced with `diterima` / `menerima` /
  `transfer masuk`.

All three are pinned in `tests/test_labels.py` so they cannot silently regress.

## 7. Forecast: three methods, no black box

`dompet/analytics/forecast.py` offers `mean`, `median`, and `weekday`. A personal cashflow
has too few points to justify a learned time-series model, and a robust daily-rate
projection is explainable and hard to fool. The window includes **zero-spend days**, so a
month with few purchases does not inflate the daily rate. `median` resists a single large
purchase; `weekday` prices in weekend-heavy spending. The method is explicit in the API
response, never hidden.

## 8. Drift detection uses a robust z-score

`dompet/analytics/drift.py` uses median + MAD rather than mean/std, so a
single outlier purchase does not permanently widen the "normal" band. When a category's history has zero
spread but the current value differs, the z-score is **saturated at 99** rather than
`inf`, so alerts stay JSON-serializable (`tests/test_drift.py`).

## 9. Post-launch fixes (debugging log)

Bugs found by an adversarial pass over realistic notification formats, each with a
regression test so it cannot silently return.

**9.1 Dotted dates read as the transaction amount (data-corrupting).**
`_DATE_TIME_RE` in `dompet/core/normalize.py` only masked `/`- and `-`-separated dates
and `:`-separated times. Notifications like `BCA: TGL 24.09.2026 TRK 50000` left the date
unmasked, so `pick_amount` read it as a bare number: **amount 24,092,026 instead of
50,000**. (The `Rp`-prefixed variants survived by accident — a currency-prefixed number
outranks bare ones.) Fix: the mask (and `parse_datetime`) now handle `dd.mm.yyyy`
(requiring a 4-digit year) and standalone dotted times `hh.mm(.ss)` (requiring a valid
hour). The guards are what keep amounts safe: `50.000.00` has no 4-digit year and
`Rp50.000` / bare `5.000` are never standalone `hh.mm`, so none of them are masked.
The slash/dash date alternative is now also digit-bounded, so reference numbers like a
PLN token `1234-5678` are no longer partially blanked (`34-56`) in descriptions.
Tests: `MaskDottedDatetimeTest`, `ParseDottedDatetimeTest`, plus two new parser fixtures
(`bca_dotted_date.txt`, `bni_dotted_datetime.txt`).

**9.2 Dedupe hash not Unicode-form-insensitive (double-count vector).**
`normalize_text` collapsed whitespace (including NBSP — `\s` matches it) and `raw_hash`
uppercased, but neither applied Unicode normalization. The same notification arriving
composed (`KAFÉ`) through one path and decomposed (`KAFE` + U+0301) through another
hashed differently, so `raw_notifications.content_hash` would not conflict and the
transaction would be stored twice. Fix: `normalize_text` now applies **NFC** before
whitespace collapsing — the hash function itself is untouched (per the rule: fix the
normalization, never widen the hash). Test: `UnicodeNormalizationTest`.

**9.3 `v_burn_rate` averaged only over days with spend.**
`AVG(daily_spend)` over days that had transactions overstates the daily rate for
sporadic spenders (one 300k purchase in 30 days → "avg daily spend 300k"), and
contradicted the forecaster, which correctly zero-fills quiet days. Fix: the view now
divides trailing-30-calendar-day spend by 30, matching the forecaster's basis; it also
exposes `days_with_spend` alongside `days_observed` (now the calendar window size).
Existing readers (`repository.burn_rate`, API `/summary`, dashboard KPIs) are
unaffected — same column names, now consistent numbers.

**9.4 Dashboard could mislabel real data as a synthetic demo.**
The "showing synthetic demo data" banner was inferred from volume + no reviewed rows,
so a real, unreviewed database would have been wrongly flagged. `list_transactions` now
exposes the ingestion source (`raw_notifications.source`, joined via `raw_id` — the column
is *not* on `transactions`; see §10.2), and the banner fires only when every loaded row
came from `scripts/seed_demo.py` (`source = 'demo'`).

**9.5 Rules→ML→Other ordering was untested.**
The categorization order was only verified interactively at build time.
`tests/test_categorizer_order.py` now pins it with a stub model: rules win over the
model, the model is consulted only when no rule matches, and a missing model degrades
to `Other` without a database.

## 10. Fixes found by actually running the stack

Everything above was found by reading and testing code in isolation. The bugs below were
only reachable by **executing** the documented commands and calling the live endpoints —
the unit suite and the `/health` smoke test were both green throughout.

**10.1 Every script in `scripts/` was broken as documented.**
`python scripts/seed_demo.py` died with `ModuleNotFoundError: No module named 'dompet'`.
Executing a file directly puts the *script's* directory (`scripts/`) on `sys.path`, not the
repo root, so the package was not importable. `python -m dompet.ml.train` worked, which is
why this went unnoticed. Each script now prepends the repo root to `sys.path`.
`tests/test_scripts_runnable.py` shells out with the exact documented invocation and
asserts the script reaches its config check, so a broken import fails the suite.

**10.2 `GET /transactions` returned 500 — `transactions.source` does not exist.**
`db/schema.sql` puts `source` on `raw_notifications`, not on `transactions`. The fix in §9.4
had guessed the wrong table, so the endpoint raised `psycopg.errors.UndefinedColumn` on
every call. It now joins `raw_notifications` and selects `rn.source`.
Guards added, because the existing ones could not catch this:
`tests/test_repository_integration.py` executes **every** repository read path against the
real schema (skipped unless a DSN and psycopg are present, so it runs in CI and in the
container but not on a bare install), and the CI smoke test now curls `/transactions`,
`/summary`, `/forecast` and `/drift` with `--fail` instead of only `/health`.

**10.3 `v_burn_rate` exposed a column nothing read.**
§9.3 added `days_with_spend` to the view, but `repository.burn_rate` still selected only
three columns, so the value never reached the API. The new DB test caught it — the column
is now selected and surfaced in `/summary`.

**10.4 Synthetic demo rows were dated in the future.**
`generate_notifications` picked the date embedded in each notification text independently of
the timestamp it was "received", so seeded rows carried `posted_at` up to ~28 days ahead
(e.g. a row dated 28 Sep imported on the 24th). That leaked future days into the trailing
30-day window, making `days_with_spend` (32) exceed `days_observed` (30). The generator now
derives the embedded date/time from `received_at`, and `v_burn_rate` also guards
`posted_at::date <= current_date` so a future-dated statement can never inflate the window.
Tests: `tests/test_synthetic.py`, plus `days_with_spend <= days_observed` in the DB test.

**10.5 Operational gaps that made "how do I run it" painful.**
The image did not copy `scripts/` or `tests/`, so the demo and in-container test commands
failed; both are copied now. The dashboard needed Streamlit, which was not part of the
compose stack and had to be installed on the host — there is now a `dashboard` service
(`Dockerfile.dashboard`, port 8501) so `docker compose up` brings up the whole app. The
trained model lived only in the container filesystem and was wiped by every rebuild; it is
now bind-mounted (`./models:/app/models`).

## 11. UI/UX pass (found by looking at the running interfaces)

Reported as "none of them shows good UI/UX". Three different things were behind that, and
only one was cosmetic.

**11.1 The dashboard never rendered at all.**
`streamlit run dompet/dashboard/app.py` crashed with `ModuleNotFoundError: No module named
'dompet'` — the third instance of the same `sys.path` trap (§10.1): Streamlit puts the
*app's* directory on the path, not the repo root. The app now prepends the repo root.

**11.2 My own verification was the deeper problem.**
I had reported the dashboard as healthy on the strength of `GET /_stcore/health` → `ok`
and `GET /` → HTTP 200. Both stayed green *while the script was raising* — Streamlit serves
its shell and reports server liveness regardless of whether the script ran. A health check
cannot detect a crashed script, so the guard is now `tests/test_dashboard_app.py`, which
executes the app with Streamlit's `AppTest` harness and asserts no uncaught exception plus
that the KPI row rendered. CI installs the dashboard requirements and runs it. The compose
healthcheck is left as liveness and now documented as such.

**11.3 The "Needs review" queue showed the entire table.**
It filtered on `is_reviewed` alone, and nothing is ever *auto*-marked reviewed, so it
listed all 253 rows — useless as a queue. It is now confidence-driven
(`repository.review_queue`: unreviewed **and** `confidence < 0.5`, worst first), which is
what the field was for.

**11.4 Currency was formatted two different ways.**
Metric cards printed Indonesian grouping (`Rp1.234.567`) while tables used Streamlit's
`NumberColumn` format string, which is US-grouped (`Rp 1,234,567`) — the same number, two
readings, on one screen. All money is now pre-formatted through `rupiah()`.

**11.5 Deprecation noise.**
`use_container_width` was deprecated in Streamlit 1.49 in favour of `width="stretch"` and
logged a warning on every rerun. `_stretch()` picks the right kwarg for the installed
version.

**11.6 The API root was a raw JSON blob.**
`GET /` returned `{"service": "dompet", ...}` to everyone, including browsers. It now
content-negotiates: `Accept: text/html` gets a styled landing page with live status pills
and links to the dashboard, docs and database UI; anything else (curl, CI, scripts) still
gets the same JSON as before. Note this template is a `str.format` string — a literal
`{id}` in the endpoint table raised `KeyError` → HTTP 500 on first try, which CI's
`curl -H "Accept: text/html"` now catches.

**11.7 `localhost:5432` in a browser looked like a bug.**
It returns `ERR_EMPTY_RESPONSE` because Postgres speaks its wire protocol there, not HTTP —
nothing is broken, but there was no way to *look at* the data. Added an `adminer` service
(port 8080) plus a note on the landing page and in the README so the port is not mistaken
for a broken web UI.

**11.8 Presentation.**
The dashboard ran on bare Streamlit defaults. It now has a dark theme matching the chart
template (`.streamlit/config.toml`), plotly_dark charts with rupiah hover labels,
an area chart instead of a flat line, and the content split into Overview / Spending /
Review tabs so the five sections stop being one long scroll. KPI labels were also corrected:
"Tracked balance" is really net tracked cashflow (Dompet only sees what it ingested), which
is now stated explicitly.
