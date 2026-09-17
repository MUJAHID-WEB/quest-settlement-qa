# Quest: Settlement Idempotency Regression Suite

**Author:** Md. Mujahidul Islam  
**Role Applied For:** AI-Native Product QA Engineer — MUST Company  
**Quest:** Prevent a Recurring Business-Flow Failure

---

## Problem Summary

A fictional weekly rewards settlement service runs every **Tuesday at 09:00 UTC**. It settles tasks completed in the window `[previous Monday 00:00 UTC, next Monday 00:00 UTC)` (upper boundary excluded). Each qualifying task earns **10 test credits**.

**Chosen Failure:** Duplicate payout on idempotent retry — when the settlement job is retried after a transient failure, it creates a second payout for already-settled task IDs, causing users to receive double credits.

---

## Project Structure

```
quest-settlement-qa/
├── README.md
├── requirements.txt
├── settlement/
│   ├── __init__.py
│   ├── models.py                      # SQLite in-memory DB schema
│   ├── settlement_service_buggy.py    # Buggy: no idempotency guard (TC-05, TC-06 FAIL)
│   └── settlement_service_fixed.py   # Fixed: idempotency key check (all tests PASS)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    # Pytest fixtures
│   ├── test_settlement_buggy.py       # Run against buggy service (shows failures)
│   └── test_settlement_fixed.py       # Run against fixed service (all pass)
└── reports/
    ├── defect_report.md
    └── release_readiness_checklist.md
```

---

## Setup

**Requirements:** Python 3.11+

```bash
cd quest-settlement-qa

# Create and activate a virtual environment (required on macOS with Homebrew Python)
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

# Install dependencies
pip install -r requirements.txt
```

---

## Running the Tests

### Demonstrate the bug (TC-05 and TC-06 will FAIL):
```bash
pytest tests/test_settlement_buggy.py -v
```

### Demonstrate the fix (all 10 tests PASS):
```bash
pytest tests/test_settlement_fixed.py -v
```

### Full run with HTML report:
```bash
pytest tests/ -v --html=reports/test_run_report.html --self-contained-html
```

---

## What Each Test Covers

| Test ID | Description | Category |
|---------|-------------|----------|
| TC-01 | Happy path: 3 tasks in window → 30 credits, 3 notifications | Happy path |
| TC-02 | Task at exact upper boundary (Mon 00:00:00 UTC) is excluded | Cut-off boundary |
| TC-03 | Task 1 second before upper boundary (Sun 23:59:59 UTC) is included | Cut-off boundary |
| TC-04 | Task at BST midnight (UTC+6) maps to correct UTC window slot | Timezone conversion |
| TC-05 | Duplicate task_id in same settlement run → counted once | Duplicate input |
| TC-06 | Settlement job retried → no new payouts created | Retry / Idempotency |
| TC-07 | Notification fails → payout persists, no rollback | Partial failure |
| TC-08 | No tasks in window → 0 credits, 0 notifications | Empty window |
| TC-09 | Task before window start is excluded | Boundary (past) |
| TC-10 | Mixed tasks: 3 in window + 2 outside → 30 credits for 3 only | Mixed window |

---

## Key Business Rules

1. Settlement window: `[window_start, window_end)` — upper boundary **excluded**
2. One payout record per `(task_id, settlement_window_start)` — idempotent
3. Credits per task: **10**
4. Notification sent **only after** successful payout commit
5. Notification failure does **not** roll back the payout

---

## AI Usage Declaration

- AI (Claude) assisted in scaffolding boilerplate DB setup, generating test case matrix, and reviewing edge-case coverage
- All business rule translations, severity judgments, and the idempotency fix design were authored and verified by the candidate
- The buggy vs. fixed service contrast was personally designed to demonstrate a realistic regression scenario
- All test assertions were reviewed manually for correctness against the stated business rules
