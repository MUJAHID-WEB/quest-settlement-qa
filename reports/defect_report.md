# Defect Report: DR-001

## Summary
**Duplicate Payout on Settlement Job Retry — Idempotency Failure in Weekly Rewards Settlement**

---

## Classification

| Field | Value |
|-------|-------|
| **Defect ID** | DR-001 |
| **Title** | Settlement job issues duplicate credits when retried for the same window |
| **Severity** | **Critical** |
| **Priority** | P1 |
| **Component** | Settlement Service / Payout Engine |
| **Reported By** | Md. Mujahidul Islam (QA) |
| **Date** | 2026-09-18 |
| **Status** | Fixed (regression test added) |

---

## Severity Rationale

**Critical** because:
1. **Financial integrity**: Users receive double credits they are not entitled to; the platform loses value at 2× the intended rate
2. **Audit failure**: Every retry creates an unreconcilable duplicate in the payout ledger
3. **Operational trigger**: ANY transient DB failure, network blip, or manual re-trigger activates the bug — not a rare edge case
4. **Invisible to users initially**: Users see extra credits and may spend them before operations can claw back, creating a support and trust crisis
5. **Regulatory exposure**: In jurisdictions treating test credits as financial instruments, duplicate payouts constitute an accounting discrepancy

---

## Business Rule Violated

> "Task IDs must be counted once; retries must not create a second payout."

The settlement window runs every **Tuesday at 09:00 UTC** for tasks completed in `[previous Monday 00:00 UTC, following Monday 00:00 UTC)`. Each qualifying task earns **10 test credits**. This payout must be idempotent: re-running the job for the same window must produce the same result as running it once.

---

## Environment

- **Service**: Settlement Service (fictional fixture; representative of production pattern)
- **DB**: SQLite (fixture); PostgreSQL in production equivalent
- **Trigger**: Settlement job re-triggered after transient failure

---

## Reproduction Steps

### Prerequisites
```bash
git clone https://github.com/MUJAHID-WEB/quest-settlement-qa.git
cd quest-settlement-qa
pip install -r requirements.txt
```

### Steps

1. Seed a task inside the settlement window:
   ```python
   seed_task(conn, "T-R-001", "U-1", datetime(2024, 1, 3, 10, 0, 0, tzinfo=timezone.utc))
   ```

2. Run settlement (first run — legitimate):
   ```python
   result = run_settlement(conn, WINDOW_START, WINDOW_END, notify_fn)
   # result: {tasks_settled: 1, credits_issued: 10}
   ```

3. **Simulate retry** (re-run for same window, e.g., after operator re-trigger):
   ```python
   result2 = run_settlement(conn, WINDOW_START, WINDOW_END, notify_fn)
   # ACTUAL: {tasks_settled: 1, credits_issued: 10}  ← BUG: should be 0
   ```

4. Check payout table:
   ```python
   payouts = get_payouts(conn)
   # ACTUAL: 2 rows for same task_id  ← BUG: should be 1 row
   # Total credits in DB: 20  ← BUG: should be 10
   ```

### Automated Reproduction
```bash
# Demonstrate the bug (TC-06 tests will show xfail XPASS becoming XFAIL):
pytest tests/test_settlement_buggy.py -v

# Confirm the fix:
pytest tests/test_settlement_fixed.py -v
```

---

## Expected vs Actual Behaviour

| Step | Expected | Actual (Buggy) |
|------|----------|----------------|
| First settlement run | 1 payout × 10 credits | 1 payout × 10 credits ✅ |
| Retry for same window | 0 new payouts, 0 credits | **1 new payout × 10 credits** ❌ |
| Total payouts in DB | 1 row | **2 rows for same task** ❌ |
| Total credits issued | 10 | **20** ❌ |
| User's credit balance | +10 | **+20** ❌ |

---

## Root Cause Analysis

### Primary Cause
The `run_settlement` function does **not check** whether a payout already exists for a given `(task_id, settlement_window_start)` pair before inserting a new row. It unconditionally executes:

```python
# BUGGY CODE (settlement_service_buggy.py, line ~94)
conn.execute(
    "INSERT INTO payouts (task_id, user_id, settlement_window_start, credits, paid_at) VALUES (?, ?, ?, ?, ?)",
    (task_id, user_id, ws, CREDITS_PER_TASK, paid_at),
)
```

No preceding `SELECT` check. No `INSERT OR IGNORE`. No `ON CONFLICT DO NOTHING`.

### Contributing Factor
The `payouts` table also lacks a `UNIQUE(task_id, settlement_window_start)` constraint, meaning the database provides no safety net. A DB-level constraint would at least raise an `IntegrityError` on duplicate insert, allowing the application to handle it — but neither layer of protection exists.

### How Retries Are Triggered in Practice
1. Settlement job times out on a slow DB write → operator re-triggers manually
2. Job scheduler crashes mid-run → cron re-fires on restart
3. Cloud function reaches execution time limit → retry policy fires
4. Network partition causes the job to complete but the "success" signal is lost → upstream triggers a retry

All of these are routine operational events, not rare failures.

---

## Evidence

### Test Run Output (Buggy Service)
```
tests/test_settlement_buggy.py::TestTC06RetryBuggyFails::test_retry_creates_no_new_payouts_BUGGY XFAIL
tests/test_settlement_buggy.py::TestTC06RetryBuggyFails::test_total_payouts_unchanged_after_retry_BUGGY XFAIL  
tests/test_settlement_buggy.py::TestTC06RetryBuggyFails::test_credits_not_doubled_on_retry_BUGGY XFAIL

# Actual DB state after retry (from conftest debug output):
# payouts table: 2 rows for task_id='T-R-001', total credits=20
```

### Test Run Output (Fixed Service — all green)
```
tests/test_settlement_fixed.py::TestTC06RetryIdempotency::test_retry_creates_no_new_payouts PASSED
tests/test_settlement_fixed.py::TestTC06RetryIdempotency::test_total_payouts_unchanged_after_retry PASSED
tests/test_settlement_fixed.py::TestTC06RetryIdempotency::test_total_credits_unchanged_after_retry PASSED
```

---

## Proposed Fix

### Application-Level (Primary Fix)

Before inserting a payout, query for an existing record:

```python
# settlement_service_fixed.py
existing = conn.execute(
    "SELECT id FROM payouts WHERE task_id = ? AND settlement_window_start = ?",
    (task_id, ws),
).fetchone()

if existing is not None:
    tasks_skipped += 1
    continue  # Already paid — skip without error
```

### Database-Level (Defence-in-Depth)

Add a `UNIQUE` constraint to the `payouts` table:

```sql
ALTER TABLE payouts ADD CONSTRAINT uq_payout_idempotency
    UNIQUE (task_id, settlement_window_start);
```

Or in schema creation:
```sql
CREATE TABLE payouts (
    ...
    UNIQUE(task_id, settlement_window_start)
);
```

Both layers together provide:
1. **App layer**: graceful skip with logging — no exception, no noise
2. **DB layer**: last-resort guard against any code path that bypasses the app check

---

## Which Release Checks Would Block This Failure

The following gate in the **Release Readiness Checklist** (see `release_readiness_checklist.md`) would block this:

- **Gate RR-04**: "Settlement idempotency regression suite passes (TC-06: retry produces 0 new payouts)"
- **Gate RR-05**: "Payouts table has UNIQUE(task_id, settlement_window_start) constraint verified in schema migration"
- **Gate RR-02**: "Code review confirms idempotency check present before any INSERT into payouts"

Without these gates, the buggy version would have shipped undetected.

---

## Regression Test

`tests/test_settlement_fixed.py::TestTC06RetryIdempotency` — 3 assertions covering:
1. `second_run.tasks_settled == 0`
2. `len(payouts_after_retry) == len(payouts_after_first)`
3. `total_credits_after_retry == total_credits_after_first`

This test must pass in all future CI runs before the settlement service is deployable.
