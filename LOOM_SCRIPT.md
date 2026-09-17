# Loom Video Script — Quest Submission (5 min max)

**Candidate:** Md. Mujahidul Islam  
**Role:** AI-Native Product QA Engineer, MUST Company

---

## Preparation (Before Recording)

1. Open two terminal tabs:
   - Tab 1: ready to run `pytest tests/test_settlement_buggy.py -v`
   - Tab 2: ready to run `pytest tests/test_settlement_fixed.py -v`
2. Open VS Code with `quest-settlement-qa/` folder
3. Have these files ready to show:
   - `settlement/settlement_service_buggy.py` (lines 60–80 visible)
   - `settlement/settlement_service_fixed.py` (lines 60–85 visible)
   - `reports/defect_report.md`
4. Open `reports/test_run_report.html` in browser

---

## Section 1 — Why This Problem (0:00–1:15)

**[Face cam on, talking to camera]**

> "I'm Mujahidul Islam, applying for the AI-Native QA role at MUST Company.
>
> For this Quest, I identified three potential failures in the weekly settlement flow. I scored them on user impact, frequency, and detection difficulty.
>
> The highest-scoring one — the one I chose — is **duplicate payout on retry**. Here's why it ranked first:
>
> Retries happen all the time in production: a DB write times out, the scheduler restarts, an operator re-triggers after an alert. When that happens, the settlement job runs again for the same window. Without an idempotency guard, every task gets paid twice. Users receive double credits. The ledger is unreconcilable.
>
> This is not a theoretical edge case. It's the most likely operational failure in any settlement system, and it's invisible until either a ledger audit or a user reports 'I got extra credits' — by which point they may have already spent them."

**[Switch to screen share — show `intent.md` scoring table briefly]**

> "My full prioritization with scores is in `intent.md`."

---

## Section 2 — Demonstrate the Bug (1:15–2:30)

**[Terminal Tab 1 visible]**

> "Let me show you the bug first."

**[Run: `pytest tests/test_settlement_buggy.py -v`]**

> "These three TC-06 tests are marked `xfail` with `strict=True`. That means they are expected to fail — they confirm the bug exists. Watch: `XFAIL`. The buggy service retries settlement for the same window and creates duplicate payout rows. Credits doubled."

**[Open `settlement_service_buggy.py`, scroll to the INSERT block]**

> "Here's the bug. Line 68: straight INSERT with no preceding check. No `SELECT` for existing payout. No UNIQUE constraint on the table. The second run inserts again, and the user's credit balance doubles."

---

## Section 3 — Demonstrate the Fix (2:30–3:30)

**[Terminal Tab 2 visible]**

> "Now the fix."

**[Run: `pytest tests/test_settlement_fixed.py -v`]**

> "18 test assertions across 10 test cases — all green. Happy path, cut-off boundaries, timezone conversion, retry idempotency, notification failure."

**[Open `settlement_service_fixed.py`, scroll to the idempotency check]**

> "The fix is here — lines 73–79. Before every INSERT, we query: does a payout already exist for this task_id and window_start? If yes, skip. We also added a UNIQUE constraint at the database level as a second line of defence. Two layers — app-level check for graceful skip, DB-level constraint as the safety net."

**[Open `reports/test_run_report.html` in browser briefly]**

> "Here's the full HTML report — 20 passed, 3 xfailed."

---

## Section 4 — AI Usage and Personal Ownership (3:30–4:30)

**[Face cam on]**

> "AI assisted me throughout — I used Claude to:
> - Generate an initial list of failure candidates from the business rules
> - Scaffold the SQLite schema boilerplate
> - Suggest the test case matrix format
>
> But I personally made every judgment call:
> - The prioritization scores — I assigned those based on my own QA experience from testing financial settlement systems
> - The idempotency fix design — two-layer defence: app check + DB constraint — that's my architecture decision
> - The severity rating 'Critical' in the defect report — I wrote that rationale from scratch
> - Every test assertion — I reviewed each one against the stated business rules
>
> When AI suggested using `db_fresh` as the fixture name, I renamed it to `db_fixed` and `db_buggy` to make the before/after contrast obvious to reviewers. That's a small thing, but it shows I'm reviewing AI output, not just accepting it."

---

## Section 5 — Limitations and Release Decision (4:30–5:00)

**[Screen share — show `directive.md` remaining gaps section]**

> "Three gaps I documented honestly:
> 1. Concurrency — two settlement jobs running simultaneously is not tested here; needs PostgreSQL + connection pool tests
> 2. Scheduler config — I test the window logic but not that the cron is actually set to 09:00 UTC Tuesday
> 3. Account state — user deactivated between task completion and settlement day is not covered
>
> My release decision: **NO-GO** until the idempotency gates pass in CI. The checklist has 24 gates. The three idempotency ones are blocking — no exceptions.
>
> Thank you."

---

## Recording Tips

- Keep terminal font large (18pt+) so test names are readable
- Pause 1 second on each `PASSED` / `XFAIL` line
- Show the bug code and fix code side-by-side if screen space allows
- Total target: **4:45–5:00** exactly
