"""
models.py — SQLite in-memory schema for the Settlement QA fixture.

Tables:
  tasks             — completed user tasks eligible for settlement
  settlement_runs   — records each settlement job execution
  payouts           — one row per (task_id, settlement_window_start) after payout
  notifications     — one row per notification attempt linked to a payout

All timestamps are stored as ISO-8601 strings in UTC.
"""

import sqlite3
from datetime import datetime, timezone


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables. Safe to call on a fresh in-memory connection."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            completed_at    TEXT NOT NULL,  -- ISO-8601 UTC
            status          TEXT NOT NULL DEFAULT 'completed'
        );

        CREATE TABLE IF NOT EXISTS settlement_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start    TEXT NOT NULL,  -- ISO-8601 UTC (inclusive)
            window_end      TEXT NOT NULL,  -- ISO-8601 UTC (exclusive)
            triggered_at    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending'  -- pending | success | failed
        );

        CREATE TABLE IF NOT EXISTS payouts (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id                 TEXT NOT NULL,
            user_id                 TEXT NOT NULL,
            settlement_window_start TEXT NOT NULL,
            credits                 INTEGER NOT NULL DEFAULT 10,
            paid_at                 TEXT NOT NULL,
            -- Idempotency key: one payout per (task_id, window_start)
            UNIQUE(task_id, settlement_window_start)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            payout_id       INTEGER NOT NULL,
            user_id         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',  -- sent | failed
            attempted_at    TEXT NOT NULL,
            FOREIGN KEY(payout_id) REFERENCES payouts(id)
        );
    """)
    conn.commit()


def seed_task(
    conn: sqlite3.Connection,
    task_id: str,
    user_id: str,
    completed_at: datetime,
) -> None:
    """Insert a single task row. completed_at must be a UTC-aware datetime."""
    if completed_at.tzinfo is None:
        raise ValueError("completed_at must be UTC-aware")
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, user_id, completed_at) VALUES (?, ?, ?)",
        (task_id, user_id, completed_at.isoformat()),
    )
    conn.commit()


def get_payouts(conn: sqlite3.Connection) -> list[dict]:
    """Return all payout rows as dicts."""
    cur = conn.execute(
        "SELECT id, task_id, user_id, settlement_window_start, credits, paid_at FROM payouts"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_notifications(conn: sqlite3.Connection) -> list[dict]:
    """Return all notification rows as dicts."""
    cur = conn.execute(
        "SELECT id, payout_id, user_id, status, attempted_at FROM notifications"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
