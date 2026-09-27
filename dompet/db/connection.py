"""Connection helper. psycopg is imported lazily so the core stays dependency-free."""

from __future__ import annotations

import os

try:  # pragma: no cover - exercised only when psycopg is installed
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]
    dict_row = None  # type: ignore[assignment]

_MISSING_MSG = (
    "psycopg is required for database access.\n"
    "Install it with:  pip install 'psycopg[binary]'"
)


def get_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set — copy .env.example to .env and fill it in.")
    return dsn


def connect(dsn: str | None = None, *, row_factory: bool = True):
    """Open a connection. Caller owns the transaction (commit / rollback / close)."""
    if psycopg is None:  # pragma: no cover
        raise RuntimeError(_MISSING_MSG)
    kwargs = {"row_factory": dict_row} if row_factory else {}
    return psycopg.connect(dsn or get_dsn(), **kwargs)
