"""Dompet HTTP API.

Endpoints
    GET  /health                      liveness + DB + model status
    POST /ingest                      ingest one notification (X-Ingest-Token when set)
    GET  /transactions                recent transactions
    GET  /summary                     burn rate, balance, category + merchant rollups
    GET  /forecast                    end-of-month balance projection
    GET  /drift                       category drift alerts
    POST /transactions/{id}/category  correct a category (feeds the learning loop)
"""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from dompet.analytics import detect_drift, forecast_month_end
from dompet.analytics.forecast import METHODS
from dompet.db import repository as repo
from dompet.db.connection import connect
from dompet.ingest import build_categorizer, ingest_text
from dompet.ml.predict import load_if_available

app = FastAPI(
    title="dompet",
    version="0.1.0",
    description="A personal finance tracker that reads bank & e-wallet notifications.",
)

_model: Any = None
_model_loaded = False


def get_model():
    """Load the categorizer once, lazily. A missing model is not fatal (rules still work)."""
    global _model, _model_loaded
    if not _model_loaded:
        _model = load_if_available()
        _model_loaded = True
    return _model


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw notification text")
    source: str = "webhook"
    received_at: datetime | None = None


class IngestResponse(BaseModel):
    status: str
    transaction_id: int | None = None
    amount: str | None = None
    direction: str | None = None
    merchant: str | None = None
    channel: str | None = None
    account: str | None = None
    posted_at: datetime | None = None
    category: str | None = None
    confidence: float | None = None
    method: str | None = None
    needs_review: bool = False
    detail: str | None = None


class CategoryUpdate(BaseModel):
    category: str
    reviewed: bool = True


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _check_token(token: str | None) -> None:
    expected = os.environ.get("INGEST_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="invalid X-Ingest-Token")


def _money(value: Any) -> str | None:
    return None if value is None else str(value)


def _row(record: dict) -> dict:
    out = dict(record)
    if isinstance(out.get("amount"), Decimal):
        out["amount"] = str(out["amount"])
    if isinstance(out.get("posted_at"), datetime):
        out["posted_at"] = out["posted_at"].isoformat()
    return out


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
# Landing page
#
# `GET /` serves HTML to browsers and JSON to everything else (curl, CI, scrapers),
# so the API keeps a machine-readable root while a human opening the port in a
# browser no longer gets a raw JSON blob.
#
# NOTE: this is a `str.format` template — every literal brace (all the CSS, and any
# `{id}`-style path) must be doubled. CI curls this page with `Accept: text/html`,
# which is what catches an escaping slip (a stray `{id}` raised KeyError -> HTTP 500).
# --------------------------------------------------------------------------- #
_LANDING_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dompet API</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:32px;
         background:#0e1117; color:#e6edf3;
         font:16px/1.55 ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif; }}
  .card {{ width:min(760px,100%); background:#161b22; border:1px solid #26303d;
           border-radius:14px; padding:32px 34px; }}
  h1 {{ margin:0 0 6px; font-size:30px; letter-spacing:-.4px; }}
  p.sub {{ margin:0 0 22px; color:#9aa7b4; }}
  .pills {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:26px; }}
  .pill {{ font-size:13px; padding:5px 11px; border-radius:999px;
           border:1px solid #26303d; background:#0e1117; color:#c3ccd6; }}
  .ok {{ color:#22c55e; border-color:#1d3a29; }} .bad {{ color:#f87171; border-color:#4a2226; }}
  h2 {{ font-size:12px; text-transform:uppercase; letter-spacing:.9px;
        color:#7d8b99; margin:26px 0 10px; }}
  .links {{ display:grid; gap:10px; }}
  a.btn {{ display:flex; justify-content:space-between; align-items:center;
           text-decoration:none; color:#e6edf3; background:#0e1117;
           border:1px solid #26303d; border-radius:10px; padding:13px 16px; }}
  a.btn:hover {{ border-color:#22c55e; }}
  a.btn span.k {{ color:#9aa7b4; font-weight:400; }}
  a.btn code {{ font-family:ui-monospace, Menlo, Consolas, monospace;
                color:#22c55e; font-size:14px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  td {{ padding:6px 0; border-bottom:1px solid #1d242e; vertical-align:top; }}
  td.m {{ font-family:ui-monospace, Menlo, Consolas, monospace; color:#c3ccd6;
          white-space:nowrap; padding-right:16px; }}
  .note {{ margin-top:22px; padding:12px 14px; border-left:3px solid #2d3748;
           background:#0e1117; color:#9aa7b4; font-size:13.5px; border-radius:0 8px 8px 0; }}
</style></head>
<body><div class="card">
  <h1>💸 Dompet API</h1>
  <p class="sub">Parses Indonesian bank &amp; e-wallet notifications, categorizes them,
     and forecasts the month. Reads live from PostgreSQL.</p>
  <div class="pills">
    <span class="pill {db_cls}">database: {db_state}</span>
    <span class="pill {model_cls}">categorizer model: {model_state}</span>
    <span class="pill">version {version}</span>
  </div>
  <h2>Interfaces</h2>
  <div class="links">
    <a class="btn" href="{dashboard}"><span class="k">Dashboard — spending, forecast, review queue</span><code>{dashboard}</code></a>
    <a class="btn" href="/docs"><span class="k">Interactive API docs (Swagger UI)</span><code>/docs</code></a>
    <a class="btn" href="{db_ui}"><span class="k">Database UI — browse the tables and views</span><code>{db_ui}</code></a>
    <a class="btn" href="/health"><span class="k">Health check (JSON)</span><code>/health</code></a>
  </div>
  <h2>Endpoints</h2>
  <table>
    <tr><td class="m">POST /ingest</td><td>Ingest one notification (needs <code>X-Ingest-Token</code> when <code>INGEST_TOKEN</code> is set)</td></tr>
    <tr><td class="m">GET /transactions</td><td>Recent transactions (<code>?limit=</code>, <code>?unreviewed=</code>)</td></tr>
    <tr><td class="m">GET /summary</td><td>Balance, burn rate, category &amp; merchant rollups</td></tr>
    <tr><td class="m">GET /forecast</td><td>Month-end projection (<code>?method=mean|median|weekday</code>)</td></tr>
    <tr><td class="m">GET /drift</td><td>Categories off their own historical trend</td></tr>
    <tr><td class="m">POST /transactions/{{id}}/category</td><td>Correct a category — feeds the training labels</td></tr>
  </table>
  <div class="note"><b>Port 5432 is not a web port.</b> PostgreSQL speaks its own wire
    protocol there, so opening it in a browser returns <code>ERR_EMPTY_RESPONSE</code>.
    Use the Database UI above to browse the data.</div>
</div></body></html>
"""


def _db_up() -> bool:
    try:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
    except Exception:
        return False
    return True


def _landing_page() -> str:
    db_up = _db_up()
    model_loaded = get_model() is not None
    return _LANDING_TEMPLATE.format(
        db_cls="ok" if db_up else "bad",
        db_state="up" if db_up else "down",
        model_cls="ok" if model_loaded else "",
        model_state="loaded" if model_loaded else "not trained (rules only)",
        version=app.version,
        dashboard=os.environ.get("DASHBOARD_URL", "http://localhost:8501"),
        db_ui=os.environ.get("DB_UI_URL", "http://localhost:8080"),
    )


@app.get("/")
def root(request: Request):
    """HTML for browsers, JSON for API clients — decided by the Accept header."""
    if "text/html" in request.headers.get("accept", "").lower():
        return HTMLResponse(_landing_page())
    return JSONResponse(
        {
            "service": "dompet",
            "docs": "/docs",
            "health": "/health",
            "summary": "/summary",
            "forecast": "/forecast",
        }
    )


@app.get("/health")
def health() -> dict:
    db_up = _db_up()
    return {
        "status": "ok" if db_up else "degraded",
        "db": "up" if db_up else "down",
        "model_loaded": get_model() is not None,
    }


@app.post("/ingest", response_model=IngestResponse, status_code=201)
def ingest(
    payload: IngestRequest,
    x_ingest_token: str | None = Header(default=None),
    conn=Depends(get_db),
) -> IngestResponse:
    _check_token(x_ingest_token)
    result = ingest_text(
        conn,
        payload.text,
        source=payload.source,
        received_at=payload.received_at,
        categorizer=build_categorizer(conn, get_model()),
    )
    tx = result.transaction
    return IngestResponse(
        status=result.status,
        transaction_id=result.transaction_id,
        amount=_money(tx.amount) if tx else None,
        direction=tx.direction.value if tx else None,
        merchant=tx.merchant_raw if tx else None,
        channel=tx.channel.value if tx else None,
        account=tx.account_label if tx else None,
        posted_at=tx.posted_at if tx else None,
        category=result.category,
        confidence=result.confidence,
        method=result.method,
        needs_review=result.needs_review,
        detail=result.detail,
    )


@app.get("/transactions")
def transactions(
    limit: int = Query(50, ge=1, le=500),
    unreviewed: bool = False,
    conn=Depends(get_db),
) -> list[dict]:
    return [_row(r) for r in repo.list_transactions(conn, limit, unreviewed_only=unreviewed)]


@app.get("/summary")
def summary(conn=Depends(get_db)) -> dict:
    burn = repo.burn_rate(conn)
    return {
        "current_balance": _money(repo.current_balance(conn)),
        "burn_rate": {
            "avg_daily_spend": _money(burn.get("avg_daily_spend")),
            "projected_monthly_spend": _money(burn.get("projected_monthly_spend")),
            "days_with_spend": burn.get("days_with_spend"),
            "days_observed": burn.get("days_observed"),
        },
        "monthly_category_spend": [
            {**r, "month": r["month"].isoformat(), "total": _money(r["total"]), "avg_tx": _money(r["avg_tx"])}
            for r in repo.monthly_category_spend(conn)
        ],
        "top_merchants": [
            {**r, "total": _money(r["total"]), "last_seen": str(r["last_seen"])}
            for r in repo.merchant_rollup(conn, limit=20)
        ],
    }


@app.get("/forecast")
def forecast(
    method: str = "mean",
    lookback_days: int = Query(30, ge=7, le=180),
    conn=Depends(get_db),
) -> dict:
    if method not in METHODS:
        raise HTTPException(status_code=400, detail=f"method must be one of {list(METHODS)}")
    daily = dict(repo.daily_cashflow(conn, days=max(lookback_days, 90)))
    result = forecast_month_end(
        daily,
        current_balance=repo.current_balance(conn),
        method=method,
        lookback_days=lookback_days,
    )
    return result.as_dict()


@app.get("/drift")
def drift(threshold: float = Query(3.5, ge=0.0), conn=Depends(get_db)) -> list[dict]:
    today_month = date.today().replace(day=1)
    current: dict[str, Any] = {}
    history: dict[str, list[Any]] = defaultdict(list)
    for row in repo.monthly_category_spend(conn, 500):
        category = row["category"]
        if not category:
            continue
        if row["month"] == today_month:
            current[category] = row["total"]
        elif row["month"] < today_month:
            history[category].append(row["total"])
    return [alert.as_dict() for alert in detect_drift(current, history, threshold=threshold)]


@app.post("/transactions/{tx_id}/category")
def set_category(tx_id: int, payload: CategoryUpdate, conn=Depends(get_db)) -> dict:
    updated = repo.set_category(conn, tx_id, payload.category, reviewed=payload.reviewed)
    if updated == 0:
        raise HTTPException(status_code=404, detail=f"transaction {tx_id} not found")
    conn.commit()
    return {"updated": updated, "category": payload.category, "reviewed": payload.reviewed}
