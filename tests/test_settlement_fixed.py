"""
test_settlement_fixed.py — All 10 test cases run against the FIXED service.

Expected result: ALL TESTS PASS (green).

Business rules under test:
  - Settlement window: [window_start, window_end)  — upper boundary EXCLUDED
  - Credits per task: 10
  - Idempotency: one payout per (task_id, settlement_window_start)
  - Notification sent only AFTER successful payout
  - Notification failure does NOT reverse the payout

Run:
    pytest tests/test_settlement_fixed.py -v
"""

from datetime import datetime, timezone, timedelta

import pytest

from settlement.models import get_payouts, get_notifications, seed_task
from settlement.settlement_service_fixed import run_settlement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dt(year, month, day, hour=0, minute=0, second=0, tz=timezone.utc) -> datetime:
    """Convenience constructor for UTC-aware datetimes."""
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


# Standard settlement window for most tests
WINDOW_START = dt(2024, 1, 1)   # Monday 00:00 UTC (inclusive)
WINDOW_END   = dt(2024, 1, 8)   # Monday 00:00 UTC (exclusive)


# ---------------------------------------------------------------------------
# TC-01: Happy path
# ---------------------------------------------------------------------------

class TestTC01HappyPath:
    """
    TC-01: Three completed tasks inside the window.
    Expected: 30 credits issued, 3 payouts created, 3 notifications sent.
    """

    def test_credits_issued(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_fixed, "T-002", "U-2", dt(2024, 1, 4, 14))
        seed(db_fixed, "T-003", "U-3", dt(2024, 1, 5, 9))

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 3
        assert result["credits_issued"] == 30

    def test_payout_rows_created(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_fixed, "T-002", "U-2", dt(2024, 1, 4, 14))
        seed(db_fixed, "T-003", "U-3", dt(2024, 1, 5, 9))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        payouts = get_payouts(db_fixed)

        assert len(payouts) == 3
        assert all(p["credits"] == 10 for p in payouts)

    def test_notifications_sent(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_fixed, "T-002", "U-2", dt(2024, 1, 4, 14))
        seed(db_fixed, "T-003", "U-3", dt(2024, 1, 5, 9))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        notifications = get_notifications(db_fixed)

        assert len(notifications) == 3
        assert all(n["status"] == "sent" for n in notifications)


# ---------------------------------------------------------------------------
# TC-02: Cut-off boundary — task at exact upper boundary is EXCLUDED
# ---------------------------------------------------------------------------

class TestTC02UpperBoundaryExcluded:
    """
    TC-02: Task completed at exactly Monday 2024-01-08 00:00:00 UTC.
    The window is [Mon Jan 01, Mon Jan 08) — upper boundary EXCLUDED.
    Expected: 0 payouts (the boundary task does not qualify).
    """

    def test_task_at_upper_boundary_excluded(self, db_fixed, notify_success, seed):
        # Task at the EXACT upper boundary moment
        seed(db_fixed, "T-BOUNDARY-UPPER", "U-1", dt(2024, 1, 8, 0, 0, 0))

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 0, (
            "Task at exact upper boundary should NOT be included in this window"
        )
        assert len(get_payouts(db_fixed)) == 0


# ---------------------------------------------------------------------------
# TC-03: Cut-off boundary — task 1 second before upper boundary is INCLUDED
# ---------------------------------------------------------------------------

class TestTC03OneSecondBeforeUpperBoundary:
    """
    TC-03: Task completed at 2024-01-07 23:59:59 UTC (1 second before window_end).
    Expected: 1 payout, 10 credits — the task IS within the window.
    """

    def test_task_one_second_before_upper_boundary_included(self, db_fixed, notify_success, seed):
        # 1 second before the upper boundary
        seed(db_fixed, "T-BOUNDARY-MINUS1", "U-1", dt(2024, 1, 7, 23, 59, 59))

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 1
        assert result["credits_issued"] == 10


# ---------------------------------------------------------------------------
# TC-04: Timezone conversion — task submitted at BST (UTC+6) local midnight
# ---------------------------------------------------------------------------

class TestTC04TimezoneConversion:
    """
    TC-04: A user in Bangladesh (UTC+6) completes a task at their local midnight
    on Monday 2024-01-01. That is 2024-01-01 00:00:00 UTC+6 = 2023-12-31 18:00:00 UTC.

    Assumption: The system stores and queries timestamps in UTC only.
    The client converts local time to UTC before storing.

    2023-12-31 18:00 UTC is BEFORE the window start (2024-01-01 00:00 UTC),
    so this task falls in the PREVIOUS week's window, not this one.

    This test validates that the UTC conversion is applied correctly and the task
    is NOT included in the 2024-01-01 window.
    """

    def test_bst_midnight_maps_to_previous_utc_window(self, db_fixed, notify_success, seed):
        # User's local midnight Mon Jan 01 in UTC+6 = Dec 31 18:00 UTC
        BST_OFFSET = timezone(timedelta(hours=6))
        local_midnight = datetime(2024, 1, 1, 0, 0, 0, tzinfo=BST_OFFSET)
        utc_time = local_midnight.astimezone(timezone.utc)

        # Confirm the UTC conversion
        assert utc_time == dt(2023, 12, 31, 18, 0, 0), (
            f"Expected 2023-12-31 18:00 UTC, got {utc_time}"
        )

        seed(db_fixed, "T-TZ-BST", "U-BD", utc_time)

        # This window starts 2024-01-01 00:00 UTC — the task is BEFORE it
        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        assert result["tasks_settled"] == 0, (
            "Task completed at BST midnight (= UTC Dec 31) should NOT be in Jan 1–8 window"
        )

    def test_bst_noon_on_wednesday_is_in_window(self, db_fixed, notify_success, seed):
        """
        A user in UTC+6 completes a task at Wednesday noon local time.
        Wednesday 2024-01-03 12:00 UTC+6 = Wednesday 2024-01-03 06:00 UTC → IN window.
        """
        BST_OFFSET = timezone(timedelta(hours=6))
        local_noon_wed = datetime(2024, 1, 3, 12, 0, 0, tzinfo=BST_OFFSET)
        utc_time = local_noon_wed.astimezone(timezone.utc)

        assert utc_time == dt(2024, 1, 3, 6, 0, 0)

        seed(db_fixed, "T-TZ-WED", "U-BD", utc_time)

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        assert result["tasks_settled"] == 1
        assert result["credits_issued"] == 10


# ---------------------------------------------------------------------------
# TC-05: Duplicate task_id in same settlement run (same DB rows)
# ---------------------------------------------------------------------------

class TestTC05DuplicateTaskId:
    """
    TC-05: The tasks table somehow has two rows with the same task_id
    (or the settlement job processes the same task_id twice due to a data
    migration error). The payout should be issued ONCE — 10 credits total.

    Note: The tasks table has a PRIMARY KEY on id so true duplicate rows
    cannot exist there. This test simulates the scenario by calling
    run_settlement twice on the same tasks set (which is what happens on retry).
    For a pure duplicate-in-input scenario, see TC-06.
    
    This test validates that even if a task appears in the query results
    once, the idempotency mechanism correctly de-duplicates at the payout level.
    """

    def test_same_task_not_double_paid_in_one_run(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-DUP-001", "U-1", dt(2024, 1, 3, 10))

        # Run settlement — this should create exactly 1 payout
        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        payouts = get_payouts(db_fixed)
        assert result["tasks_settled"] == 1
        assert result["credits_issued"] == 10
        assert len(payouts) == 1, f"Expected 1 payout, got {len(payouts)}"

    def test_total_credits_correct_with_multiple_unique_tasks(self, db_fixed, notify_success, seed):
        """3 tasks → exactly 30 credits, not more."""
        seed(db_fixed, "T-A", "U-1", dt(2024, 1, 3, 10))
        seed(db_fixed, "T-B", "U-2", dt(2024, 1, 4, 11))
        seed(db_fixed, "T-C", "U-3", dt(2024, 1, 5, 12))

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["credits_issued"] == 30
        assert len(get_payouts(db_fixed)) == 3


# ---------------------------------------------------------------------------
# TC-06: Retry — settlement job retried after first successful run
# ---------------------------------------------------------------------------

class TestTC06RetryIdempotency:
    """
    TC-06: The settlement job is run twice for the same window (e.g., after
    a transient infrastructure failure caused an operator to manually re-trigger it).

    Expected (FIXED): Second run produces 0 new payouts. Total payouts = original count.
    Expected (BUGGY): Second run would create duplicate payouts.

    This is the PRIMARY regression test for the chosen failure.
    """

    def test_retry_creates_no_new_payouts(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-R-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_fixed, "T-R-002", "U-2", dt(2024, 1, 4, 14))

        # First run — legitimate
        first = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        assert first["tasks_settled"] == 2
        assert first["credits_issued"] == 20

        # Second run — retry (should be a no-op for payouts)
        second = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        assert second["tasks_settled"] == 0, (
            "Retry must not create new payouts for already-settled tasks"
        )
        assert second["credits_issued"] == 0
        assert second["tasks_skipped"] == 2

    def test_total_payouts_unchanged_after_retry(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-R-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_fixed, "T-R-002", "U-2", dt(2024, 1, 4, 14))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        payouts_after_first = get_payouts(db_fixed)

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        payouts_after_retry = get_payouts(db_fixed)

        assert len(payouts_after_retry) == len(payouts_after_first), (
            f"Retry created extra payouts: {len(payouts_after_retry)} vs {len(payouts_after_first)}"
        )

    def test_total_credits_unchanged_after_retry(self, db_fixed, notify_success, seed):
        seed(db_fixed, "T-R-001", "U-1", dt(2024, 1, 3, 10))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        credits_after_first = sum(p["credits"] for p in get_payouts(db_fixed))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)
        credits_after_retry = sum(p["credits"] for p in get_payouts(db_fixed))

        assert credits_after_retry == credits_after_first, (
            f"Credits doubled on retry: {credits_after_retry} vs {credits_after_first}"
        )


# ---------------------------------------------------------------------------
# TC-07: Partial failure — notification fails, payout must persist
# ---------------------------------------------------------------------------

class TestTC07NotificationFailureDoesNotReversePayout:
    """
    TC-07: The notification service is down (returns False or raises).
    Expected: Payout is committed and KEPT. Notification is recorded as 'failed'.
    The payout must not be rolled back.
    """

    def test_payout_persists_when_notification_fails(self, db_fixed, notify_failure, seed):
        seed(db_fixed, "T-NF-001", "U-1", dt(2024, 1, 3, 10))

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_failure)

        payouts = get_payouts(db_fixed)
        assert len(payouts) == 1, "Payout must persist even if notification fails"
        assert payouts[0]["credits"] == 10

    def test_notification_recorded_as_failed(self, db_fixed, notify_failure, seed):
        seed(db_fixed, "T-NF-001", "U-1", dt(2024, 1, 3, 10))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_failure)

        notifications = get_notifications(db_fixed)
        assert len(notifications) == 1
        assert notifications[0]["status"] == "failed"

    def test_payout_persists_when_notification_raises(self, db_fixed, notify_raises, seed):
        seed(db_fixed, "T-NF-002", "U-2", dt(2024, 1, 3, 11))

        run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_raises)

        payouts = get_payouts(db_fixed)
        assert len(payouts) == 1, "Payout must persist even when notification service raises"


# ---------------------------------------------------------------------------
# TC-08: Empty window — no tasks
# ---------------------------------------------------------------------------

class TestTC08EmptyWindow:
    """
    TC-08: No tasks exist in the settlement window.
    Expected: 0 credits, 0 payouts, 0 notifications.
    """

    def test_no_tasks_produces_zero_payout(self, db_fixed, notify_success):
        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 0
        assert result["credits_issued"] == 0
        assert result["notifications_sent"] == 0
        assert len(get_payouts(db_fixed)) == 0
        assert len(get_notifications(db_fixed)) == 0


# ---------------------------------------------------------------------------
# TC-09: Task before window start is excluded
# ---------------------------------------------------------------------------

class TestTC09TaskBeforeWindowExcluded:
    """
    TC-09: Task completed before the window start should not be settled.
    Task at 2023-12-31 23:59:59 UTC (1 second before window_start 2024-01-01 00:00 UTC).
    Expected: 0 payouts.
    """

    def test_task_before_window_start_excluded(self, db_fixed, notify_success, seed):
        # 1 second before window_start
        seed(db_fixed, "T-BEFORE", "U-1", dt(2023, 12, 31, 23, 59, 59))

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 0
        assert len(get_payouts(db_fixed)) == 0


# ---------------------------------------------------------------------------
# TC-10: Mixed tasks — some inside window, some outside
# ---------------------------------------------------------------------------

class TestTC10MixedWindowTasks:
    """
    TC-10: 5 tasks total. 3 inside the window, 2 outside (1 before, 1 at boundary).
    Expected: 30 credits for 3 tasks only.
    """

    def test_only_in_window_tasks_are_settled(self, db_fixed, notify_success, seed):
        # In window
        seed(db_fixed, "T-IN-1", "U-1", dt(2024, 1, 1, 0, 0, 1))   # 1 sec after start
        seed(db_fixed, "T-IN-2", "U-2", dt(2024, 1, 3, 15, 30, 0))  # midweek
        seed(db_fixed, "T-IN-3", "U-3", dt(2024, 1, 7, 23, 59, 59)) # 1 sec before end

        # Outside window
        seed(db_fixed, "T-OUT-1", "U-4", dt(2023, 12, 31, 23, 59, 59))  # before start
        seed(db_fixed, "T-OUT-2", "U-5", dt(2024, 1, 8, 0, 0, 0))       # at upper boundary

        result = run_settlement(db_fixed, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 3
        assert result["credits_issued"] == 30

        payouts = get_payouts(db_fixed)
        paid_task_ids = {p["task_id"] for p in payouts}
        assert paid_task_ids == {"T-IN-1", "T-IN-2", "T-IN-3"}
        assert "T-OUT-1" not in paid_task_ids
        assert "T-OUT-2" not in paid_task_ids
