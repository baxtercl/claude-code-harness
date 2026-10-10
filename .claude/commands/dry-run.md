---
description: Force a simulated run before any destructive or externally visible operation.
---

# /dry-run

Applies the **dry-run-guard** skill to the operation at hand.

1. Name the operation and what it touches.
2. Translate it to its simulation: `--dry-run`, `--plan`, `--check`, `--noop`, or a `SELECT COUNT(*)` before a `DELETE`.
3. Run the simulation and show the full output: what changes, how many records, estimated cost and time.
4. Wait for an explicit "yes, run it for real".
5. Run it and report something observable: a URL, a hash, a row count, a log line.
