---
status: draft
updated: 2026-05-22
---

# Import mapping

## Starting points

As an organiser, I want a fresh mapping to start populated with one
entry per source question, so that I do not transcribe source identifiers
by hand.

As an organiser, I want to re-fetch the source schema after the form
changes, so that new questions appear in the mapping without overwriting
hand-edits.

As an organiser, I want to copy another event's mapping onto mine, so
that I do not start from scratch when the source form is reused between
editions.

## Editing

As an organiser, I want full control over what each source question maps
to, so that I can express targets, fan-in, and identity rules without a
specialised editor.

As an organiser, I want in-progress mapping edits to survive an
accidental tab close, so that I do not lose mid-edit work.

As an organiser, I want a way to mark source questions as deliberately
unmapped, so that removed or irrelevant questions do not pollute later
validation.

## Validation

As an organiser, I want the mapping checked for mistakes that the bare
schema cannot describe, so that bad mappings never reach apply or pull.

As an organiser, I want validation errors to point at the exact location
in the mapping with a short explanation, so that I can fix them without
guessing.
