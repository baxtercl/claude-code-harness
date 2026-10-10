---
name: prd
description: Use before implementing a non-trivial feature, especially one that crosses repositories or changes an API, event or data contract. Writes or updates a Product Requirements Document that any future session can implement from, and starts with a mandatory Phase 0 that verifies every inherited claim against the code.
---

# Writing a PRD

A PRD is the executable specification of a feature. The test of a good one: **a fresh session can implement the feature by reading only the PRD and its links**, without rediscovering the terrain or re-deciding the design.

## When to write one

Write a PRD when **at least two** of these hold:

- **(a)** There is a decision with real, hard-to-reverse alternatives.
- **(b)** It crosses a contract: two repositories, or an API, streaming or data schema change.
- **(c)** It absorbs two or more tickets, or defines how a roadmap success criterion is accepted.
- **(d)** It takes more than two days, or has phases where one result can invalidate the next.

Otherwise it stays a ticket: a fix with a known cause, a hygiene chore, running an existing runbook, or a decision better recorded as an ADR.

If the work is a deferred part of a feature that already has a PRD, **update that PRD** instead of writing a new one. Two documents describing the same feature means neither is the source of truth.

## Phase 0: verify the premise (mandatory, per PRD)

Before writing the "Current state" section, check every claim inherited from the ticket, the roadmap, a previous plan or a catalog against the code. Produce this table:

| Claim | Command run | Evidence (`path:line` + quote) | Verdict |
|---|---|---|---|
| "Price history is missing" | `rg -n "price_history" src/` | `src/repo/prices.py:31` "def get_price_history(" | False |

If a premise falls, the PRD changes scope or is not written.

### Why this is not optional

Agents (and people) write confident diagnoses that turn out to be false: a feature reported as "missing" that already exists, a policy "not published" that an endpoint serves. Verifying once at the start of a session is not enough, because later claims slip through. **The check is applied claim by claim.**

## Steps

1. Run Phase 0 and keep the table.
2. Copy `templates/prd-template.md` to `docs/prd/PRD-<ticket-id>-<slug>.md`.
3. Fill in all sections. Four are mandatory and are where most PRDs cut corners:
   - **Current state:** every `path:line` with a literal quote of that line.
   - **Acceptance criteria:** each one with the command that verifies it and what output counts as failure.
   - **Not covered:** what this PRD explicitly leaves open.
   - **Monthly cost delta:** in USD, with the source of the number.
4. Link the PRD from the backlog ticket.
5. When implemented, set `Status: Implemented` with the commit or PR. Do not delete it.

## Work-in-progress limit

At most three PRDs in `Ready to implement` at the same time. For a small team, a large catalog of "ready" specs does not speed anything up; it becomes another document nobody reads in full.
