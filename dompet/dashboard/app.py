"""Dompet dashboard.

Run:  streamlit run dompet/dashboard/app.py
Needs DATABASE_URL (see .env.example). When every row came from
`scripts/seed_demo.py`, the dashboard labels itself as a synthetic demo.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# `streamlit run dompet/dashboard/app.py` puts the *app's* directory on sys.path
# (`.../dompet/dashboard`), not the repo root, so `import dompet` fails without this.
# Same trap as scripts/*.py — see decision_log.md §10.1 / §11.1.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dompet.analytics import detect_drift, forecast_month_end  # noqa: E402
from dompet.analytics.forecast import METHODS  # noqa: E402
from dompet.db import repository as repo  # noqa: E402
from dompet.db.connection import connect  # noqa: E402
from dompet.ingest import LOW_CONFIDENCE_THRESHOLD  # noqa: E402

st.set_page_config(
    page_title="Dompet — money tracker",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --------------------------------------------------------------------------- #
# Compatibility
# --------------------------------------------------------------------------- #
def _stretch() -> dict:
    """Streamlit 1.49 deprecated `use_container_width` in favour of `width='stretch'`.

    Passing the deprecated kwarg still works but logs a warning on every rerun.
    """
    try:
        major, minor = (int(part) for part in st.__version__.split(".")[:2])
    except ValueError:
        return {"use_container_width": True}
    return {"width": "stretch"} if (major, minor) >= (1, 49) else {"use_container_width": True}


STRETCH = _stretch()


# --------------------------------------------------------------------------- #
# Data access (cached — each loader opens and closes its own connection)
# --------------------------------------------------------------------------- #
def _fetch(fn):
    conn = connect()
    try:
        return fn(conn)
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def load_summary() -> dict:
    def q(c):
        return {
            "balance": repo.current_balance(c),
            "burn": repo.burn_rate(c),
            "monthly": repo.monthly_category_spend(c),
            "merchants": repo.merchant_rollup(c, 15),
            "sources": repo.source_mix(c),
        }

    return _fetch(q)


@st.cache_data(ttl=60, show_spinner=False)
def load_daily_cashflow(days: int) -> list[tuple]:
    return _fetch(lambda c: repo.daily_cashflow(c, days))


@st.cache_data(ttl=60, show_spinner=False)
def load_review_queue(limit: int = 200) -> list[dict]:
    return _fetch(lambda c: repo.review_queue(c, limit, below=LOW_CONFIDENCE_THRESHOLD))


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def rupiah(value) -> str:
    """Indonesian grouping (Rp1.234.567) — used everywhere, including tables.

    Streamlit's NumberColumn format string uses US grouping (Rp 1,234,567), which
    contradicted the metric cards, so amounts are pre-formatted as text instead.
    """
    if value is None:
        return "—"
    return "Rp" + f"{Decimal(str(value)):,.0f}".replace(",", ".")


def thousands(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(str(value)):,.0f}".replace(",", ".")


PLOTLY_LAYOUT = dict(template="plotly_dark", margin=dict(l=0, r=0, t=10, b=0))


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
try:
    summary = load_summary()
except Exception as exc:  # surface config/connection problems plainly
    st.error(
        f"**Could not read the database.**\n\n`{exc}`\n\n"
        "Set `DATABASE_URL` and run `python scripts/init_db.py`."
    )
    st.stop()

total_tx = sum(row["n_tx"] for row in summary["sources"])
if not total_tx:
    st.info(
        "**No transactions yet.** Load a statement, wire up the IMAP poll, or run "
        "`python scripts/seed_demo.py --n 250 --days 60` for synthetic demo data."
    )
    st.stop()

sources = {row["source"] for row in summary["sources"]}
demo_like = sources == {"demo"}
first_seen = min(row["first_seen"] for row in summary["sources"])
last_seen = max(row["last_seen"] for row in summary["sources"])

queue = load_review_queue()
months = sorted({row["month"] for row in summary["monthly"]}, reverse=True)


# --------------------------------------------------------------------------- #
# Sidebar — controls and context
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.subheader("Forecast")
    method = st.selectbox(
        "Method", METHODS, index=0,
        help="mean: average daily net · median: ignores one-off spikes · weekday: per-day-of-week.",
    )
    lookback = st.slider("Lookback (days)", min_value=7, max_value=120, value=30, step=1)

    st.divider()
    st.subheader("Data")
    st.caption(f"**{total_tx:,}** transactions".replace(",", "."))
    st.caption(f"{first_seen:%d %b %Y} → {last_seen:%d %b %Y}")
    st.caption("Sources: " + ", ".join(f"{row['source']} ({row['n_tx']})" for row in summary["sources"]))
    if demo_like:
        st.caption("⚠️ Synthetic demo data")
    st.divider()
    if st.button("Refresh data", **STRETCH):
        st.cache_data.clear()
        st.rerun()


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("💸 Dompet")
st.caption(
    "Bank & e-wallet notifications → parsed, categorized and forecast. "
    "Reads live from PostgreSQL through the reporting views."
)
if demo_like:
    st.info(
        "Showing **synthetic demo data** from `scripts/seed_demo.py` — the numbers are "
        "illustrative, not real spending."
    )


# --------------------------------------------------------------------------- #
# KPIs
# --------------------------------------------------------------------------- #
daily = dict(load_daily_cashflow(max(lookback, 90)))
forecast = forecast_month_end(
    daily, current_balance=summary["balance"], method=method, lookback_days=lookback
)

c1, c2, c3, c4 = st.columns(4)
c1.metric(
    "Net tracked cashflow",
    rupiah(summary["balance"]),
    help="Sum of every tracked transaction (credits − debits). Not a bank balance — "
    "Dompet only sees what it has ingested.",
)
c2.metric(
    "Avg daily spend",
    rupiah(summary["burn"].get("avg_daily_spend")),
    help=f"Spend ÷ 30 calendar days ({summary['burn'].get('days_with_spend')} had spending).",
)
c3.metric("Projected month spend", rupiah(summary["burn"].get("projected_monthly_spend")))
c4.metric(
    f"Projected balance · {forecast.month_end:%d %b}",
    rupiah(forecast.projected_balance),
    delta=None if forecast.days_until_zero is None else f"{forecast.days_until_zero}d at this rate",
    delta_color="inverse" if forecast.days_until_zero is not None else "normal",
    help=f"Extrapolated with the '{forecast.method}' method over "
    f"{forecast.remaining_days} remaining days.",
)


# --------------------------------------------------------------------------- #
# Body
# --------------------------------------------------------------------------- #
tab_overview, tab_spending, tab_review = st.tabs(
    ["Overview", "Spending", "Review" + (f" ({len(queue)})" if queue else "")]
)

with tab_overview:
    st.subheader("Daily net cashflow")
    if daily:
        series = pd.DataFrame(
            [{"day": day, "net": float(net)} for day, net in sorted(daily.items())]
        )
        fig = px.area(series, x="day", y="net")
        fig.update_traces(
            line_color="#22c55e", fillcolor="rgba(34,197,94,0.15)",
            hovertemplate="%{x|%a %d %b %Y}<br><b>Rp%{y:,.0f}</b><extra></extra>",
        )
        fig.add_hline(y=0, line_dash="dot", line_color="grey")
        fig.update_layout(**PLOTLY_LAYOUT, height=320, yaxis_title=None, xaxis_title=None)
        st.plotly_chart(fig, **STRETCH)
        st.caption(
            f"Forecast method **{forecast.method}** · average daily net "
            f"{rupiah(forecast.avg_daily_net)} · {forecast.remaining_days} days to month end."
        )
    else:
        st.caption("No cashflow recorded in this window.")

    st.subheader("Category drift")
    today_month = date.today().replace(day=1)
    current, history = {}, defaultdict(list)
    for row in summary["monthly"]:
        if not row["category"]:
            continue
        if row["month"] == today_month:
            current[row["category"]] = row["total"]
        elif row["month"] < today_month:
            history[row["category"]].append(row["total"])
    alerts = detect_drift(current, history)
    if alerts:
        for alert in alerts:
            icon = "🔺" if alert.direction == "up" else "🔻"
            st.warning(
                f"{icon} **{alert.category}** is {rupiah(alert.current)} this month, "
                f"against a usual {rupiah(alert.baseline_median)} "
                f"(robust z = {alert.robust_z:.1f})."
            )
    else:
        st.caption("Nothing is off its own historical trend this month.")

with tab_spending:
    left, right = st.columns((3, 2))
    with left:
        st.subheader("Spending by category")
        if months:
            latest = months[0]
            cat_rows = [r for r in summary["monthly"] if r["month"] == latest]
            df = pd.DataFrame(
                [
                    {"category": r["category"] or "Uncategorized", "total": float(r["total"])}
                    for r in cat_rows
                ]
            )
            if not df.empty:
                fig = px.bar(df, x="total", y="category", orientation="h")
                fig.update_traces(
                    marker_color="#22c55e",
                    hovertemplate="<b>Rp%{x:,.0f}</b><extra></extra>",
                )
                fig.update_layout(
                    **PLOTLY_LAYOUT,
                    height=380,
                    yaxis={"categoryorder": "total ascending", "title": None},
                    xaxis_title=None,
                )
                st.plotly_chart(fig, **STRETCH)
            st.caption(f"Month: {latest:%B %Y}")
        else:
            st.caption("No spend recorded yet.")

    with right:
        st.subheader("Top merchants")
        if summary["merchants"]:
            merchants = pd.DataFrame(
                [
                    {
                        "merchant": row["merchant"],
                        "category": row["category"],
                        "total": rupiah(row["total"]),
                        "txns": row["n_tx"],
                    }
                    for row in summary["merchants"]
                ]
            )
            st.dataframe(merchants, hide_index=True, **STRETCH)
        else:
            st.caption("No merchant data yet.")

with tab_review:
    st.subheader("Needs review")
    st.caption(
        f"Unreviewed transactions the categorizer was unsure about "
        f"(confidence < {LOW_CONFIDENCE_THRESHOLD}). Correcting one makes it a training label."
    )
    if queue:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "when": f"{row['posted_at']:%Y-%m-%d %H:%M}",
                        "account": row["account"],
                        "merchant": row["merchant"] or (row["description"] or "")[:40],
                        "suggested": row["category"],
                        "confidence": row["confidence"],
                        "amount": rupiah(row["amount"]),
                        "id": row["id"],
                    }
                    for row in queue
                ]
            ),
            hide_index=True,
            **STRETCH,
        )
        st.caption(
            "Fix with `POST /transactions/{id}/category` "
            '(e.g. `{"category": "Shopping", "reviewed": true}`).'
        )
    else:
        st.success("Nothing waiting — every transaction was categorized confidently.")

st.divider()
st.caption(
    "Dompet runs on its owner's own notifications. Never commit real statement data."
)
