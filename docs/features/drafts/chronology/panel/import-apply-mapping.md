---
status: draft
updated: 2026-05-22
---

# Apply mapping — provision event entities

As an organiser, I want to choose how an apply run reacts when it would
touch entities that already exist, so that I can re-run apply on an event
with hand-tuned entities without losing my work.

As an organiser, I want to see what an apply run would do before it
commits, so that I can abort a wildly wrong run before it touches
anything.

As an organiser, I want the preview to flag destructive consequences, so
that I'm not surprised when previously-imported content is detached.

As an organiser, I want a fully-destructive apply mode to require an
extra confirmation tied to the event itself, so that it cannot be
triggered by a stray click.

As an organiser, I want an apply run to either fully succeed or fully
roll back, so that a half-finished apply never leaves the event in an
inconsistent state.

As an organiser, I want a per-category summary of what an apply run
created, updated, and skipped, so that I can audit the result and jump
to the entities it touched.
