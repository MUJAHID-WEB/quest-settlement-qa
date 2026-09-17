"""
settlement_service_buggy.py — INTENTIONALLY BROKEN implementation.

BUG: When the settlement job is retried (e.g., after a transient failure),
     it does NOT check whether a task has already been paid out.
     This causes duplicate payouts: users receive 10 credits twice for the
     same completed task.

This file exists to make TC-05 and TC-06 FAIL, proving the regression.
Do NOT use in production.
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
) -> None:
    """
    Attempt to send a notification for a completed payout.
    If notification_fn raises or returns False, status is recorded as 'failed'.
    Notification failure does NOT roll back the payout (correct behaviour kept here).
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


def run_settlement(
    conn: sqlite3.Connection,
    window_start: datetime,
    window_end: datetime,
    notification_fn: Callable[[str], bool] | None = None,
) -> dict:
    """
    BUG VERSION: Settles all tasks in [window_start, window_end).
    Does NOT check for existing payouts — retrying this function creates
    duplicate payout rows (IntegrityError is swallowed if UNIQUE is absent;
    or the UNIQUE constraint itself is the only guard, but we INSERT blindly).

    Returns a summary dict: {tasks_settled, credits_issued, notifications_sent}.
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
        """,
        (ws, we),
    )
    tasks = cur.fetchall()

    tasks_settled = 0
    credits_issued = 0
    notifications_sent = 0

    paid_at = _now_utc()

    for task_id, user_id in tasks:
        # ❌ BUG: No idempotency check. Just INSERT — will fail silently or
        #    succeed depending on whether UNIQUE constraint exists.
        #    We deliberately DROP the UNIQUE constraint in the buggy table
        #    to allow true double inserts.
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
                _notify(conn, payout_id, user_id, notification_fn)
                notifications_sent += 1

        except sqlite3.IntegrityError:
            # In the buggy version this should not be reached because we use
            # a table without the UNIQUE constraint (see conftest_buggy fixture)
            pass

    return {
        "tasks_settled": tasks_settled,
        "credits_issued": credits_issued,
        "notifications_sent": notifications_sent,
    }
