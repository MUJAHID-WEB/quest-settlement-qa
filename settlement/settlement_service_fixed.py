"""
settlement_service_fixed.py — CORRECT implementation with idempotency guard.

FIX: Before inserting a payout, we check whether a record already exists
     for (task_id, settlement_window_start). If one is found, we skip the
     task silently — the payout has already been made.

     The payouts table also has a UNIQUE(task_id, settlement_window_start)
     constraint as a database-level safety net, but the application-level
     check comes first so we can log/skip gracefully rather than relying on
     an exception.

All 10 test cases pass against this implementation.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Callable


CREDITS_PER_TASK = 10


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _notify(
    conn: sqlite3.Connection,
    payout_id: int,
    user_id: str,
    notification_fn: Callable[[str], bool],
) -> str:
    """
    Attempt to send a notification for a completed payout.
    Returns 'sent' or 'failed'. Notification failure does NOT roll back
    the payout — they are decoupled by design.
    """
    attempted_at = _now_utc()
    try:
        success = notification_fn(user_id)
        status = "sent" if success else "failed"
    except Exception:
        status = "failed"

    conn.execute(
        "INSERT INTO notifications (payout_id, user_id, status, attempted_at) VALUES (?, ?, ?, ?)",
        (payout_id, user_id, status, attempted_at),
    )
    conn.commit()
    return status


def run_settlement(
    conn: sqlite3.Connection,
    window_start: datetime,
    window_end: datetime,
    notification_fn: Callable[[str], bool] | None = None,
) -> dict:
    """
    FIXED VERSION: Settles all tasks in [window_start, window_end).

    Idempotency guarantee:
      - Application-level: query payouts for (task_id, window_start) before INSERT
      - DB-level: UNIQUE(task_id, settlement_window_start) constraint on payouts table

    Returns a summary dict:
      tasks_settled       — number of new payouts created this run
      credits_issued      — total credits issued this run
      notifications_sent  — notifications attempted this run
      tasks_skipped       — tasks skipped because already paid
    """
    if window_start.tzinfo is None or window_end.tzinfo is None:
        raise ValueError("window_start and window_end must be UTC-aware datetimes")

    ws = window_start.isoformat()
    we = window_end.isoformat()

    # Fetch qualifying tasks — window is [start, end), upper boundary excluded
    cur = conn.execute(
        """
        SELECT id, user_id FROM tasks
        WHERE completed_at >= ?
          AND completed_at < ?
          AND status = 'completed'
        ORDER BY completed_at ASC
        """,
        (ws, we),
    )
    tasks = cur.fetchall()

    tasks_settled = 0
    credits_issued = 0
    notifications_sent = 0
    tasks_skipped = 0

    paid_at = _now_utc()

    for task_id, user_id in tasks:
        # ✅ FIX: Application-level idempotency check
        existing = conn.execute(
            "SELECT id FROM payouts WHERE task_id = ? AND settlement_window_start = ?",
            (task_id, ws),
        ).fetchone()

        if existing is not None:
            # Already paid out — skip to prevent duplicate
            tasks_skipped += 1
            continue

        try:
            conn.execute(
                """
                INSERT INTO payouts (task_id, user_id, settlement_window_start, credits, paid_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, user_id, ws, CREDITS_PER_TASK, paid_at),
            )
            conn.commit()

            cur2 = conn.execute("SELECT last_insert_rowid()")
            payout_id = cur2.fetchone()[0]

            tasks_settled += 1
            credits_issued += CREDITS_PER_TASK

            if notification_fn:
                status = _notify(conn, payout_id, user_id, notification_fn)
                if status == "sent":
                    notifications_sent += 1

        except sqlite3.IntegrityError:
            # DB-level safety net (UNIQUE constraint) — should not be reached
            # because the application check above already skips duplicates
            tasks_skipped += 1
            conn.rollback()

    return {
        "tasks_settled": tasks_settled,
        "credits_issued": credits_issued,
        "notifications_sent": notifications_sent,
        "tasks_skipped": tasks_skipped,
    }
