"""Postgres access layer. Raw SQL only — no ORM, so the SQL is visible in-repo."""

from dompet.db.connection import connect, get_dsn  # noqa: F401
