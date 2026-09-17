"""
conftest.py — Shared pytest fixtures for the Settlement QA suite.

Provides:
  - db_fixed    : in-memory SQLite connection with full schema (UNIQUE constraint on payouts)
  - db_buggy    : in-memory SQLite connection WITHOUT the UNIQUE constraint on payouts
                  (simulates a service that never added the DB-level guard either)
  - window_*    : standard settlement window datetimes for the fictional Tuesday run
  - notify_*    : mock notification callables for happy/failure scenarios
"""

import sqlite3
from datetime import datetime, timezone

import pytest

from settlement.models import create_schema, seed_task


# ---------------------------------------------------------------------------
# Settlement window constants
# ---------------------------------------------------------------------------
# Fictional settlement: Tuesday 2024-01-09 09:00 UTC
# Settles tasks in [Monday 2024-01-01 00:00 UTC, Monday 2024-01-08 00:00 UTC)
WINDOW_START = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)   # inclusive
WINDOW_END   = datetime(2024, 1, 8, 0, 0, 0, tzinfo=timezone.utc)   # exclusive


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_fixed() -> sqlite3.Connection:
    """
    Fresh in-memory SQLite DB with the FULL schema including the
    UNIQUE(task_id, settlement_window_start) constraint on payouts.
    Used for tests against settlement_service_fixed.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_buggy() -> sqlite3.Connection:
    """
    Fresh in-memory SQLite DB WITHOUT the UNIQUE constraint on payouts.
    This simulates the full buggy scenario where neither the app nor the DB
    prevents duplicate inserts.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Create schema but override payouts table to remove UNIQUE constraint
    conn.executescript("""
        CREATE TABLE tasks (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            completed_at    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'completed'
        );

        CREATE TABLE settlement_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start    TEXT NOT NULL,
            window_end      TEXT NOT NULL,
            triggered_at    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending'
        );

        CREATE TABLE payouts (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id                 TEXT NOT NULL,
            user_id                 TEXT NOT NULL,
            settlement_window_start TEXT NOT NULL,
            credits                 INTEGER NOT NULL DEFAULT 10,
            paid_at                 TEXT NOT NULL
            -- ❌ NO UNIQUE constraint — bug scenario
        );

        CREATE TABLE notifications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            payout_id       INTEGER NOT NULL,
            user_id         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempted_at    TEXT NOT NULL
        );
    """)
    conn.commit()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Window fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def window():
    """Returns (window_start, window_end) for the standard test settlement."""
    return WINDOW_START, WINDOW_END


# ---------------------------------------------------------------------------
# Notification mock callables
# ---------------------------------------------------------------------------

@pytest.fixture
def notify_success():
    """Always succeeds."""
    def _fn(user_id: str) -> bool:
        return True
    return _fn


@pytest.fixture
def notify_failure():
    """Always fails (simulates 500/timeout)."""
    def _fn(user_id: str) -> bool:
        return False
    return _fn


@pytest.fixture
def notify_raises():
    """Raises an exception (simulates network timeout)."""
    def _fn(user_id: str) -> bool:
        raise ConnectionError("Notification service unreachable")
    return _fn


# ---------------------------------------------------------------------------
# Seed helpers exposed as fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def seed():
    """Returns the seed_task function for convenience in tests."""
    return seed_task
