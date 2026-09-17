# directive.md — Final Working Instructions

**Candidate:** Md. Mujahidul Islam  
**Role:** AI-Native Product QA Engineer — MUST Company  
**Quest:** Prevent a Recurring Business-Flow Failure  
**Status:** Complete

---

## Objective

Identify, reproduce, and build a regression check for a high-impact failure in the fictional weekly rewards settlement service. The chosen failure is **duplicate payout on settlement job retry** — a critical idempotency gap that causes users to receive double credits whenever the settlement job is re-triggered for the same window.

---

## Scope

**In scope:**
- Settlement payout idempotency (TC-05, TC-06)
- Settlement window boundary enforcement — UTC (TC-02, TC-03, TC-04)
- Notification/payout decoupling on partial failure (TC-07)
- Empty window and mixed-task boundary cases (TC-08, TC-09, TC-10)
- Happy path baseline (TC-01)

**Out of scope:**
- Real production systems, live financial data, or real user accounts
- Notification delivery retry queue design
- Multi-currency or multi-region settlement orchestration
- Performance or load testing of the settlement job

---

## Business Rules (Fictional Settlement Service)

1. Settlement runs every **Tuesday at 09:00 UTC**
2. Window covers tasks completed in **[previous Monday 00:00 UTC, following Monday 00:00 UTC)** — upper boundary is **excluded**
3. Each qualifying task earns **10 test credits**
4. Task IDs must be counted **once** — retries must not create a second payout
5. A notification is sent **only after** a successful payout commit
6. Notification failure must **not** reverse the payout

---

## Requirements

### Functional
- `run_settlement(conn, window_start, window_end, notification_fn)` must be idempotent
- Re-running with the same `(task_id, settlement_window_start)` must skip with no new payout row
- Window query uses `>=` for start (inclusive) and `<` for end (exclusive)
- All timestamps stored and compared in UTC

### Quality Gates (see `reports/release_readiness_checklist.md` for full list)
- TC-06 must pass: retry produces 0 new payouts
- TC-05 must pass: duplicate task_id counted once
- TC-07 must pass: notification failure does not reverse payout
- `payouts` table must have `UNIQUE(task_id, settlement_window_start)` constraint

---

## Assumptions

The following assumptions were made during test design. These would require confirmation against a real implementation before production use:

| # | Assumption | Where Applied |
|---|------------|---------------|
| A1 | **Client-side UTC conversion.** Task `completed_at` is stored in UTC. The client application converts local time to UTC before writing to the database. The settlement service does not perform timezone conversion — it queries UTC directly. | TC-04 |
| A2 | **`status = 'completed'` is the only eligibility filter.** No other task state (e.g., `verified`, `approved`) gates payout eligibility. | TC-01 through TC-10 |
| A3 | **Account state does not block settlement.** A user whose account is deactivated or suspended after completing a task but before the settlement run still receives credits for the completed task. If this assumption is wrong, an additional eligibility query is needed. | Not tested (documented gap) |
| A4 | **Admin cannot change credits-per-task between completion and settlement.** The 10-credit rate is fixed at settlement time, not at task completion time. | TC-01 through TC-10 |
| A5 | **Notification is fire-and-forget with single attempt.** There is no retry queue for failed notifications. Missed notifications are recorded as `status='failed'` and require a separate backfill process. | TC-07 |
| A6 | **No concurrent settlement runs for the same window.** Two instances of the settlement job will not run simultaneously for the same `window_start`. Race-condition idempotency (two concurrent INSERTs) is protected by the DB UNIQUE constraint but is not explicitly tested in this fixture. | Documented gap |

---

## Completion Criteria

| Criterion | Requirement | Met? |
|-----------|-------------|------|
| ≥ 8 test cases documented | 10 test cases with inputs and expected outcomes | ✅ |
| Happy path covered | TC-01 | ✅ |
| Cut-off boundary covered | TC-02, TC-03 | ✅ |
| Timezone conversion covered | TC-04 | ✅ |
| Duplicate input covered | TC-05 | ✅ |
| Retry covered | TC-06 | ✅ |
| Partial failure covered | TC-07 | ✅ |
| Regression fails on buggy service | TC-06 xfail tests in test_settlement_buggy.py | ✅ |
| Regression passes on fixed service | All tests in test_settlement_fixed.py | ✅ |
| Defect report produced | reports/defect_report.md | ✅ |
| Release readiness checklist | reports/release_readiness_checklist.md | ✅ |
| Automated tests runnable by reviewer | `pip install -r requirements.txt && pytest -v` | ✅ |

---

## Project Structure

```
quest-settlement-qa/
├── README.md                          ← Setup and run instructions
├── requirements.txt                   ← pytest, freezegun, pytest-html
├── intent.md                          ← Problem selection rationale
├── directive.md                       ← This file
├── settlement/
│   ├── __init__.py
│   ├── models.py                      ← SQLite schema + seed helpers
│   ├── settlement_service_buggy.py    ← Broken implementation (no idempotency)
│   └── settlement_service_fixed.py   ← Correct implementation
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    ← Shared fixtures (DB, window, notify mocks)
│   ├── test_settlement_fixed.py       ← 10 test cases — all PASS
│   └── test_settlement_buggy.py       ← Regression evidence — TC-06 XFAIL on buggy
└── reports/
    ├── defect_report.md               ← DR-001: Formal defect report with RCA
    └── release_readiness_checklist.md ← 24 go/no-go gates
```

---

## How to Run

### Setup
```bash
git clone <YOUR_GITHUB_REPO_URL>
cd quest-settlement-qa

# Create and activate a virtual environment (required on macOS with Homebrew Python)
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

pip install -r requirements.txt
```

### Demonstrate the bug (TC-06 xfail tests confirm regression exists)
```bash
pytest tests/test_settlement_buggy.py -v
```
Expected: TC-06 tests show `XFAIL` (test fails as expected — confirming the bug).

### Demonstrate the fix (all tests green)
```bash
pytest tests/test_settlement_fixed.py -v
```
Expected: All tests `PASSED`.

### Full run with HTML report
```bash
pytest tests/ -v --html=reports/test_run_report.html --self-contained-html
open reports/test_run_report.html
```

---

## Release-Readiness Decision

**Decision: NO-GO until idempotency gates (RR-05 through RR-09) are verified.**

The fixed service passes all gates. The buggy service fails RR-07, RR-08, and RR-09. No deployment should proceed without:
1. Code review confirming the idempotency check is in the deployed version
2. DB schema verification that `UNIQUE(task_id, settlement_window_start)` exists
3. Full regression suite green in CI

---

## Remaining Gaps & Limitations

1. **Fixture is SQLite, not PostgreSQL.** The UNIQUE constraint behaviour is identical, but PostgreSQL's transaction isolation and concurrent write behaviour (e.g., two settlement jobs running simultaneously) is not tested here. A production-grade regression suite would add concurrency tests.

2. **Notification delivery depth not tested.** This fixture only tests that the payout persists when the notification mock returns False or raises. A real suite would also test: notification retry queue, delivery status webhook, and missing notification backfill for the failure window.

3. **Scheduler / cron timing not tested.** The test suite does not verify that the settlement job is actually scheduled for Tuesday 09:00 UTC. This is an infrastructure concern that should be covered by an integration test in the deployment pipeline.

4. **No account state changes tested.** The brief mentions "account and login changes" as a test concern. This fixture does not cover permission changes between task completion and settlement (e.g., a user's account is deactivated after completing a task but before Tuesday's settlement run).

5. **freezegun not used for scheduler timing.** The boundary tests (TC-02, TC-03) validate the window query logic directly with seeded UTC timestamps rather than mocking the clock. This is sufficient for the business rule test but would not catch a misconfigured scheduler.

---

## Effort Log

| Activity | Estimated Time |
|----------|---------------|
| Problem selection and scoring | 45 min |
| Fixture design and schema | 30 min |
| Buggy service implementation | 20 min |
| Fixed service implementation | 25 min |
| Test case writing (10 cases) | 60 min |
| Defect report | 30 min |
| Release readiness checklist | 25 min |
| intent.md + directive.md | 45 min |
| AI-assisted review and iteration | 30 min |
| Loom video recording | 30 min |
| **Total** | **~6 hours** |

---

## Results / Handoff Appendix

### Artifact Links

| Artifact | Location |
|----------|----------|
| Test project (runnable) | `quest-settlement-qa/` — clone repo and run `pytest` |
| Fixed service | `settlement/settlement_service_fixed.py` |
| Buggy service (regression evidence) | `settlement/settlement_service_buggy.py` |
| All 10 test cases | `tests/test_settlement_fixed.py` |
| Buggy regression tests | `tests/test_settlement_buggy.py` |
| Defect report DR-001 | `reports/defect_report.md` |
| Release readiness checklist | `reports/release_readiness_checklist.md` |
| intent.md | `intent.md` |
| Loom video | [Loom link — add before submission] |

> **Before submitting:** Add your GitHub repo URL above and verify all links open without login.

### Reproduction Steps for Reviewer

```bash
# 1. Clone the repository
git clone <YOUR_GITHUB_REPO_URL>
cd quest-settlement-qa

# 2. Install dependencies (Python 3.11+ required)
pip install -r requirements.txt

# 3. See the bug: TC-06 xfail tests confirm duplicate payouts on retry
pytest tests/test_settlement_buggy.py -v

# 4. See the fix: all 10 test cases pass against fixed service
pytest tests/test_settlement_fixed.py -v

# 5. Generate HTML report
pytest tests/ -v --html=reports/test_run_report.html --self-contained-html
```

### Actual Test Results

| Suite | Result | Detail |
|-------|--------|--------|
| `test_settlement_fixed.py` | **18 PASSED** | 10 test cases × multiple assertions — all green |
| `test_settlement_buggy.py` | **2 PASSED + 3 XFAILED** | TC-06 XFAIL confirms duplicate-payout bug exists |
| **Combined** | **20 passed, 3 xfailed** | `pytest tests/ -v` (see `reports/test_run_report.html`) |

### AI Contribution and Corrections

| Task | AI Contribution | My Correction / Verification |
|------|----------------|------------------------------|
| Problem scoring matrix structure | Generated format | Personally scored all dimensions based on QA experience |
| DB schema boilerplate | Generated initial schema | Reviewed and added UNIQUE constraint, adjusted column types |
| Test case skeleton for TC-04 | Generated basic timezone test | Corrected UTC offset logic; added second sub-test for in-window case |
| conftest fixture names | Suggested `db_fresh` | Renamed to `db_fixed` / `db_buggy` for clarity |
| `_notify` helper | Generated initial version | Added return value (status string) needed by fixed service |
| Defect report structure | Generated section headers | Rewrote severity rationale and root cause analysis from QA perspective |

### Limitations Statement

All data, fixtures, task IDs, user IDs, and business rules in this submission are **synthetic**. No real user data, real financial transactions, API keys, credentials, or confidential employer information is included. The settlement service is a fictional representative implementation for hiring evaluation purposes only.
