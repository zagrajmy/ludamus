---
status: draft
updated: 2026-09-13
points: 16
depends: [04]
---

# Session kinds

## Naming

As an organiser, I want what used to be a proposal category called a
session kind throughout the panel, so that the name says what it is: a
taxonomy of sessions.

As a maintainer, I want the rename to reach the model field, the related
names, the DTOs and the filter keys, so that the codebase speaks one
vocabulary instead of saying "kind" in the panel and "category" everywhere
underneath.

As a participant, I want a session's kind shown with the same wording as
before, so that a rename inside the panel changes nothing for me.

As an automation client, I want kind-related tools named after kinds, so
that tool names match the concept.

As a Polish-speaking organiser, I want kinds called "rodzaj" in the panel
and "rodzaj atrakcji" publicly, so that the vocabulary stays consistent.

## What a kind carries

As an organiser, I want a kind to carry durations, participant bounds,
waitlist behaviour, and its session questions, so that everything intrinsic
to that type of session is in one place.

As an organiser, I want a kind to carry no dates and no description, so
that I never mistake it for a call for proposals.

As a proposer, I want kinds presented by name alone, so that the choice is
quick.

As an organiser, I want to be stopped from removing a kind that sessions
already use, so that the programme does not lose its labels.

## What it touches

This is the full rename, not panel copy. Half of it would leave two
vocabularies in one codebase, which is what the current
`ProposalCategory`-as-CFP-config confusion cost us in the first place. The
`proposal_category` table name stays — a table rename buys nothing and costs
a lock.

- `ProposalCategory` → `SessionKind`; `Session.category` → `Session.kind`
  (field and column, a reversible `RenameField`);
  `related_name="proposal_categories"` → `session_kinds`;
  `SessionFieldRequirement.category_requirements` → `kind_requirements`
  (the other two `category_requirements` related names are already gone —
  `PersonalDataFieldRequirement` in 01, `TimeSlotRequirement` in 02).
- `ProposalCategoryDTO` → `SessionKindDTO` and the protocols, services,
  repository methods and mills that name it; `SubmissionRepository`'s
  category methods follow.
- URL names `panel:cfp*` → `panel:session-kinds*`; templates
  `panel/cfp.html` and friends; `cfp_tags.cfp_status` goes with the kind's
  dates (a kind has no status to badge).
- The public tag filter key `__category` becomes `__kind`
  (`event_presentation.py`, `chronology/event.html`); the visible label
  stays "rodzaj atrakcji". A shared link carrying the old key filters
  nothing rather than erroring — the programme still lists in full.
- MCP: `list_proposal_categories` / `create_proposal_category` become
  `list_session_kinds` / `create_session_kind`, descriptions reworded.
- Konwencik export keeps its `type` column; only the Python that feeds it is
  renamed.
- The kind edit page keeps name, durations, participant bounds, waitlist
  mode and the session-field requirements; the description input goes, and
  the wizard's kind card shows the name only. `apply_dates_to_categories`
  goes from the proposal settings form and service with the dates.
