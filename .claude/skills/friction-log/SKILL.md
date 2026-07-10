---
name: friction-log
description: >-
  Do a real task while recording where the agent got stuck, then write a short
  friction log. Use when the user asks for a "friction log", wants to capture
  DX pain, or says "log the friction while you do X". Distinct from PAPERCUTS.md
  (quick one-liners logged in the moment) — this narrates one task end to end.
---

# friction-log

Run the task the user asked for. While you work, note every point of friction:
a retried command, a misleading error, an undocumented step, a stale cache, a
gotcha. Friction is the deliverable — don't hide it to look smooth.

## Rules

- Extract the task from the user's message; don't pre-clarify. Log uncertainty
  instead of asking.
- Read any URLs in the prompt before starting.
- A build/test failure is a friction signal, not a stop. Retry ~3× then log it.
- Write entries as you go, not from memory at the end. No `[TBD]` placeholders.

## Output

Write `friction-<task>.md` with:

- **Task** — one line, plus model and date.
- **Log** — chronological entries, each: what you expected → what happened →
  how it resolved. Prefix severity: 🟢 smooth · 🟡 minor · 🔴 blocking.
- **Fixes** — one bullet per 🟡/🔴 with a concrete suggestion.

Keep it terse. Skip any section that would be empty.
