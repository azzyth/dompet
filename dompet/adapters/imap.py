"""IMAP adapter — the primary, server-friendly ingestion path.

A dedicated inbox receives bank / e-wallet notifications (forwarded from your
phone or from the bank's email alerts). This polls it and feeds every message
body into the same ingestion pipeline as everything else.
"""

from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime

from dompet.ingest import ingest_many

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _decode(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        parts = decode_header(raw.decode("utf-8", "replace"))
    else:
        parts = decode_header(raw)
    out = []
    for text, enc in parts:
        out.append(text.decode(enc or "utf-8", "replace") if isinstance(text, bytes) else text)
    return "".join(out)


def _body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition", "")
            ):
                return _decode(part.get_payload(decode=True))
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = _decode(part.get_payload(decode=True))
                return _WS_RE.sub(" ", _TAG_RE.sub(" ", html)).strip()
        return ""
    return _decode(msg.get_payload(decode=True))


def fetch_notifications(
    host: str,
    user: str,
    password: str,
    *,
    port: int = 993,
    folder: str = "INBOX",
    search: str = "UNSEEN",
    limit: int = 200,
) -> list[tuple[str, datetime]]:
    """Return ``(body_text, received_at)`` for matching messages, oldest first."""
    results: list[tuple[str, datetime]] = []
    with imaplib.IMAP4_SSL(host, port) as client:
        client.login(user, password)
        client.select(folder)
        status, data = client.search(None, search)
        if status != "OK":
            return []
        ids = data[0].split()[-limit:]
        for msg_id in ids:
            status, payload = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            msg = email.message_from_bytes(payload[0][1])
            text = _WS_RE.sub(" ", _body(msg)).strip()
            if not text:
                continue
            try:
                received = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
            except (TypeError, ValueError):
                received = None
            results.append((text, received or datetime.now()))
    results.sort(key=lambda r: r[1])
    return results


def poll_once(source: str = "imap") -> dict[str, int]:
    """Read IMAP config from the environment, poll, and ingest into Postgres."""
    from dompet.db.connection import connect

    host = os.environ["IMAP_HOST"]
    user = os.environ["IMAP_USER"]
    password = os.environ["IMAP_PASSWORD"]
    items = fetch_notifications(
        host,
        user,
        password,
        port=int(os.environ.get("IMAP_PORT", "993")),
        folder=os.environ.get("IMAP_FOLDER", "INBOX"),
        search=os.environ.get("IMAP_SEARCH", "UNSEEN"),
    )
    conn = connect()
    try:
        return ingest_many(conn, items, source=source)
    finally:
        conn.close()
