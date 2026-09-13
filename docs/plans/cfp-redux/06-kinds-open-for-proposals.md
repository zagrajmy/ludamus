---
status: draft
updated: 2026-09-13
points: 5
depends: [05]
---

# Kinds a call accepts

## Choosing what the call takes

As an organiser, I want to say which kinds my call for proposals accepts,
so that I can keep taking workshop proposals while the lecture programme is
already full.

As an organiser, I want a kind's openness set where I edit the kind, so
that I do not go looking for a separate screen to close one.

As an organiser, I want every kind to keep accepting proposals unless I say
otherwise, so that nothing closes by surprise on the day this lands.

As an organiser, I want the call to count as closed when no kind accepts
proposals, so that proposers are not sent into a wizard with nothing to
choose.

As an organiser, I want a call whose end precedes its start refused, so
that I cannot save a period that never opens.

As an organiser, I want a call with no dates set to count as closed, so
that an event that has never configured intake does not accidentally
collect proposals.

## Proposing

As a proposer, I want to choose among the kinds the call accepts, so that I
am not offered something the organiser has closed.

As a proposer, I want the kind chosen for me when only one is open, so that
I am not asked a question with one answer.

As an anonymous proposer, I want to propose without an account when the
event allows anonymous proposals, so that the lowest barrier wins and I
learn about the account requirement before I fill anything in.

## Reading kinds elsewhere

As a participant, I want to filter the programme by kind, so that a closed
call changes nothing about browsing.

As an automation client, I want to list and create kinds regardless of
intake, so that seeding an event works before proposals open.

## What it touches

- `SessionKind.accepts_proposals`, a boolean defaulting to true, a checkbox
  on the kind form, and a column on the kinds list. The migration sets it
  true everywhere, so existing events carry over unchanged.
- `Event.is_proposal_active` keeps its meaning — both dates set and now
  between them — and the wizard additionally requires at least one kind
  with `accepts_proposals`. Unset or half-set dates stay closed, as today.
- The proposal settings form refuses an end before its start; the two
  columns stay nullable.
- The wizard's kind step lists only accepting kinds and is skipped when
  exactly one accepts, as it is today with one kind.
- Anonymity stays event-wide in `EventProposalSettings`, so
  `ProposeWizardMixin.dispatch` keeps deciding before the wizard starts and
  an anonymous proposer is never bounced to a login page mid-wizard, after
  entering personal data. Per-kind anonymity would create exactly that
  bounce, and nobody has asked for it.
- The description shown on the wizard's first page stays event-wide too.
