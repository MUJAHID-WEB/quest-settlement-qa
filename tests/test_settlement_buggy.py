"""
test_settlement_buggy.py — Tests run against the BUGGY service.

Purpose: Demonstrate that TC-06 (retry idempotency) and TC-05 (duplicate credits)
FAIL against the buggy implementation, proving the regression exists.

Expected result:
  - TC-06 tests: FAIL (duplicate payouts created on retry)
  - All other tests: PASS (the bug only manifests on retry)

This file is part of the evidence trail showing the bug before the fix.

Run:
    pytest tests/test_settlement_buggy.py -v
"""

from datetime import datetime, timezone, timedelta

import pytest

from settlement.models import get_payouts, get_notifications, seed_task
from settlement.settlement_service_buggy import run_settlement

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def dt(year, month, day, hour=0, minute=0, second=0, tz=timezone.utc) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


WINDOW_START = dt(2024, 1, 1)
WINDOW_END   = dt(2024, 1, 8)


# ---------------------------------------------------------------------------
# TC-01 (Buggy): Happy path — passes even in buggy version (single run)
# ---------------------------------------------------------------------------

class TestTC01HappyPathBuggy:
    def test_credits_issued_single_run(self, db_buggy, notify_success, seed):
        seed(db_buggy, "T-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_buggy, "T-002", "U-2", dt(2024, 1, 4, 14))
        seed(db_buggy, "T-003", "U-3", dt(2024, 1, 5, 9))

        result = run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)

        assert result["tasks_settled"] == 3
        assert result["credits_issued"] == 30


# ---------------------------------------------------------------------------
# TC-06 (Buggy): Retry FAILS — duplicate payouts created ← KEY REGRESSION
# ---------------------------------------------------------------------------

class TestTC06RetryBuggyFails:
    """
    These tests are EXPECTED TO FAIL against the buggy service.
    They prove the bug: retrying settlement duplicates payouts.

    pytest will mark these FAILED — that is intentional and demonstrates
    the regression that the fix resolves.
    """

    @pytest.mark.xfail(
        reason="BUG: Buggy service has no idempotency guard — retry creates duplicate payouts",
        strict=True,
    )
    def test_retry_creates_no_new_payouts_BUGGY(self, db_buggy, notify_success, seed):
        seed(db_buggy, "T-R-001", "U-1", dt(2024, 1, 3, 10))
        seed(db_buggy, "T-R-002", "U-2", dt(2024, 1, 4, 14))

        # First run
        run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)

        # Second run (retry) — BUG: creates duplicate payouts
        second = run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)

        # This assertion FAILS on the buggy service (second.tasks_settled == 2, not 0)
        assert second["tasks_settled"] == 0, (
            f"BUG CONFIRMED: Retry settled {second['tasks_settled']} tasks again (expected 0)"
        )

    @pytest.mark.xfail(
        reason="BUG: Buggy service doubles total payouts on retry",
        strict=True,
    )
    def test_total_payouts_unchanged_after_retry_BUGGY(self, db_buggy, notify_success, seed):
        seed(db_buggy, "T-R-001", "U-1", dt(2024, 1, 3, 10))

        run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)
        count_after_first = len(get_payouts(db_buggy))

        run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)
        count_after_retry = len(get_payouts(db_buggy))

        # BUG: count_after_retry == 2 (doubled), not 1
        assert count_after_retry == count_after_first, (
            f"BUG CONFIRMED: Payout count doubled from {count_after_first} to {count_after_retry}"
        )

    @pytest.mark.xfail(
        reason="BUG: Buggy service doubles credits on retry",
        strict=True,
    )
    def test_credits_not_doubled_on_retry_BUGGY(self, db_buggy, notify_success, seed):
        seed(db_buggy, "T-R-001", "U-1", dt(2024, 1, 3, 10))

        run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)
        credits_after_first = sum(p["credits"] for p in get_payouts(db_buggy))

        run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_success)
        credits_after_retry = sum(p["credits"] for p in get_payouts(db_buggy))

        # BUG: credits_after_retry == 20 (doubled from 10)
        assert credits_after_retry == credits_after_first, (
            f"BUG CONFIRMED: Credits doubled from {credits_after_first} to {credits_after_retry}"
        )


# ---------------------------------------------------------------------------
# TC-07 (Buggy): Notification failure — this works correctly even in buggy
# ---------------------------------------------------------------------------

class TestTC07NotificationBuggy:
    def test_payout_persists_when_notification_fails(self, db_buggy, notify_failure, seed):
        """The notification/payout decoupling is correct in both versions."""
        seed(db_buggy, "T-NF-001", "U-1", dt(2024, 1, 3, 10))

        run_settlement(db_buggy, WINDOW_START, WINDOW_END, notify_failure)

        payouts = get_payouts(db_buggy)
        assert len(payouts) == 1
        assert payouts[0]["credits"] == 10
