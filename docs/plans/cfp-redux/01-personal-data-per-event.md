---
status: draft
updated: 2026-09-13
points: 13
depends: []
---

# Personal data asked once per event

## Configuring the questions

As an organiser, I want each personal-data question to apply to every
proposer at my event, so that I configure it once rather than per kind of
session.

As an organiser, I want to mark a personal-data question as required, so
that a proposal cannot be submitted without an answer.

As an organiser, I want a question that was required for every kind to stay
required, and one that was required for only some kinds to become optional,
so that the switch to one setting never blocks a submission that used to go
through.

As an organiser, I want to set the order in which personal-data questions
are asked, so that the form reads the way I planned it.

As an organiser, I want a yes/no question to be impossible to mark required
— refused by the database, not only by the form — so that no import,
migration or type change can leave one behind that forces a proposer to
answer "yes".

As an organiser, I want to see how many people have answered a question, so
that I know what removing it would cost.

As an organiser, I want to be stopped from removing a question people have
already answered, so that collected data is not lost by accident.

## Proposing

As a proposer, I want to be asked the same personal details whatever I
propose, so that I never fill in the same information twice at one event.

As a proposer, I want to give my personal details before choosing what I
propose, so that my details are on file even if I change my mind about the
kind.

As a proposer, I want required questions enforced when I submit, so that the
organiser gets what they asked for.

As a proposer, I want my previous answers for this event prefilled, so that
a second proposal costs me nothing extra.

## Recording on someone's behalf

As an organiser entering a facilitator's details myself, I want no question
forced on me, so that I can record what I know and fill the rest later.

As an organiser editing a proposal, I want the same optional treatment for
each facilitator's details, so that I am not blocked by data I do not have.

As a maintainer, I want one place that decides which questions are required
for whom, so that "never required when someone records data on another
person's behalf" is a rule with an owner rather than a habit repeated at
every call site.

## What it touches

- Migration: `PersonalDataField.is_required` (default false), backfilled
  true only when every kind in the field's event has a
  `PersonalDataFieldRequirement` row for that field with `is_required`
  true. A missing row counts as not required, and a field whose event has
  no kinds stays optional — read the kinds, not just the rows the field
  happens to have, or `all()` over an empty set makes a field nobody
  attached required for everyone. This is the strict-to-optional direction,
  whose failure mode an organiser fixes in two clicks, unlike a form that
  silently starts rejecting submissions. `order` takes the maximum
  requirement order. The requirement table is dropped.
- `CheckConstraint` on `PersonalDataField`: not
  (`field_type = checkbox` and `is_required`). The same migration zeroes
  `is_required` on every checkbox field after the backfill and before the
  constraint is added, so the backfill cannot leave behind a row the
  constraint rejects. The repository normalises `is_required` to false when
  the type is checkbox on every write, so a type change from text to
  checkbox cannot violate it. The form guard stays as the message the
  organiser reads.
- `PersonalDataFieldForm` and the create/edit pages gain "Required" and
  order inputs; the per-kind selects disappear. The repository persists
  `order`.
- The kind settings page loses its "Host Data Fields" block.
- One builder in `gates/web/django/dynamic_fields.py` takes the event's
  fields and who is answering, and returns the `(field, is_required)` pairs:
  the proposer gets each field's own flag, anyone recording data on someone
  else's behalf gets false. It replaces `requirement_fields` and the five
  sites that hardcode `[(field, False) for field in fields]`
  (`proposal_edit` ×2, `facilitator_fields` ×2, `chronology/views`).
- `ProposeSessionService.get_personal_requirements` takes the event, not the
  kind. The wizard's personal step moves before the kind step.
- Delete guard: refuse when `PersonalDataFieldValue` rows exist for the
  field; the row-action reason says so. `FieldUsageSummary` counts values,
  not kinds.
