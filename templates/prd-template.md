# PRD-<TICKET-ID>: <short feature title>

**Status:** Draft | In review | Ready to implement | Implemented | Discarded
**Priority:** P0 | P1 | P2 | P3
**Repositories:** <list>
**Tickets:** <IDs>
**Author / date:** <name> / <YYYY-MM-DD>

---

## 0. Phase 0: premise verification

| Claim | Command run | Evidence (`path:line` + quote) | Verdict |
|---|---|---|---|
| | | | |

## 1. Summary

One to three sentences: what is built and for whom.

## 2. Problem

Why this exists, where the finding came from (feedback, metric, audit), and the cost of not doing it.

## 3. Goals and non-goals

**Goals** (measurable where possible):
- ...

**Non-goals** (explicitly out of scope):
- ...

## 4. Current state

How the system behaves today in the affected area.

> **Mandatory: literal quotes.** Every `path:line` comes with the exact text of that line. Open the file and read it; never copy a reference from another document. This is the section where invented facts hide most easily and get cited most often.
>
> **No unmeasured root causes.** If a cause is not verified, state it as a hypothesis and start the technical design with a measurement phase whose result can invalidate the rest of this PRD.

## 5. Expected behavior

The flow from the user's point of view, step by step, including loading, empty, error and success states.

## 6. Technical design

- **Frontend:** components and hooks to create or change (with paths), state, contract with the backend.
- **Backend:** endpoints (method, route, auth), services and repositories, request and response contracts.
- **Data:** tables, columns, migrations.
- **Rollout:** feature flag, default value, activation plan.
- **Alternatives considered** and why they were discarded.

## 7. Acceptance criteria

> **Mandatory: a verification command per criterion.** If you cannot write the command, the criterion cannot fail, so it is not a criterion. Rewrite it or delete it.

| # | Criterion | Verification command | What counts as failure |
|---|---|---|---|
| 1 | | | |

**Sabotage test.** Name what you would have to break for these checks to turn red. If you cannot name it, the check proves nothing. An instrument that cannot fail is not evidence.

Every number quoted in this PRD carries `(measured YYYY-MM-DD, command, environment)`.

## 8. Test plan

Unit, integration and end-to-end coverage, and which evidence is captured.

## 9. Dependencies and risks

Blocking tickets, decisions, ADRs, technical risks and mitigations.

### 9.1 Not covered by this PRD

**Mandatory.** List what this PRD does not solve, even if it is close. A ticket cannot be closed with "moved to X" unless X exists as an open ticket with its own definition of done.

## 10. Estimate

Size (S/M/L or days), split by repository. Anything above L is split before approval.

### 10.1 Monthly cost delta (USD)

**Mandatory.** If the delta is positive, name what gets turned off in exchange.

| Item | USD/month | Source of the number |
|---|---:|---|
| | | |
| **Net delta** | | |

## 11. Links

- Tickets:
- ADRs:
- Related PRDs:
