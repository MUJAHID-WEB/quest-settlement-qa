# intent.md — Why This Problem?

**Candidate:** Md. Mujahidul Islam  
**Role:** AI-Native Product QA Engineer — MUST Company  
**Quest:** Prevent a Recurring Business-Flow Failure

---

## Problem Chosen

**Duplicate payout on settlement job retry — idempotency failure.**

When the weekly settlement job is retried (for any operational reason), it re-pays already-settled task IDs, issuing 10 credits twice per task instead of once.

---

## Alternatives Considered

I identified three realistic failure classes in the fictional settlement service and ranked them before choosing one to solve deeply.

### Problem 1 (Chosen): Duplicate Payout on Retry
**Description:** Settlement job has no idempotency guard. Retrying for the same window creates duplicate payout rows.

| Dimension | Score (1–5) | Notes |
|-----------|-------------|-------|
| User impact | 5 | Users receive double credits; platform loses value at 2× rate |
| Frequency / Likelihood | 5 | Any transient DB failure, scheduler crash, or manual re-trigger activates it |
| Effort to detect without tests | 5 | Invisible until ledger audit or user report |
| Effort to fix | 2 | One idempotency check + DB UNIQUE constraint |
| **Total** | **17/20** | **Ranked 1st** |

### Problem 2: Cut-off Boundary Mis-inclusion (≤ vs <)
**Description:** A task completed at exactly `Monday 00:00:00 UTC` (the upper boundary) is included in the wrong settlement window because the query uses `<=` instead of `<`.

| Dimension | Score | Notes |
|-----------|-------|-------|
| User impact | 3 | Affects users who complete tasks at midnight exactly — uncommon but deterministic |
| Frequency / Likelihood | 3 | Happens every week for any task at exact midnight |
| Effort to detect without tests | 4 | Off-by-one — easy to miss in code review |
| Effort to fix | 1 | Single operator change in SQL query |
| **Total** | **11/20** | **Ranked 2nd** |

### Problem 3: Notification Failure Rolls Back Payout
**Description:** If the notification HTTP call fails (timeout/500), the code rolls back the entire database transaction — user loses credits even though they completed the task.

| Dimension | Score | Notes |
|-----------|-------|-------|
| User impact | 4 | Users lose earned credits due to an unrelated notification failure |
| Frequency / Likelihood | 3 | Depends on notification service stability — less common than DB retries |
| Effort to detect without tests | 3 | Requires end-to-end test with notification failure injection |
| Effort to fix | 3 | Requires decoupling notification from payout transaction |
| **Total** | **13/20** | **Ranked 3rd** |

---

## Why Problem 1 Ranked First

Three compounding reasons made Problem 1 the most important to solve:

**1. Operational trigger is routine, not exceptional.**  
Retry scenarios (transient DB write failure, scheduler restart, manual re-trigger after alert) happen in every production system. This is not a theoretical edge case — it is a matter of when, not if. My experience auditing financial systems at Spritztech confirmed that settlement retries occur during every major deployment window or infrastructure event.

**2. Impact compounds over time.**  
Each retry doubles the outstanding credits. If a settlement window covers 500 tasks and the job is retried twice (once from a crash, once from an overzealous operator), 1,500 payout records exist for 500 actual tasks. The audit cost grows with every incident.

**3. It is the canonical fintech idempotency bug — reviewers recognize it.**  
The MUST Company role explicitly tests understanding of "idempotent retries." Choosing this problem demonstrates direct alignment with the role's stated responsibilities and the assessment rubric ("business understanding: do you test against how the business and its users actually work, not only against the ticket?").

---

## Uncertainty Acknowledged

I do not have access to MUST Company's actual production logs, incident history, or real user data. My prioritization is based on:
- The business rules stated in the Quest brief
- General patterns from my experience testing financial settlement systems at Spritztech and DevFirm
- Published knowledge about idempotency failures in payout systems

I have labelled all fixtures as synthetic and all scenarios as representative, not historical.

---

## Intended Value

**What this solves:** A class of financial integrity failures that become invisible until a ledger audit — at which point investigation, credit clawback, and user communication create significant operational overhead.

**What this does not solve (non-goals):**
- Real notification delivery monitoring or retry queuing
- Multi-currency credit accounting
- Cross-timezone settlement window orchestration (multi-region)
- Production deployment of this fixture

---

## How AI Was Used in Problem Selection

I used Claude (AI) to:
- Generate an initial list of ~8 possible failure classes from the business rules
- Help structure the scoring matrix format
- Draft the scoring rationale text which I then edited for accuracy

I personally made the final prioritization decision, chose the problem dimensions, assigned scores based on my own QA experience, and verified that the chosen problem was the highest-value target for the role's evaluation criteria.
