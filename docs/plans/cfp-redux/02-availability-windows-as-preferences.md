---
status: draft
updated: 2026-09-13
points: 8
depends: [01]
---

# Availability windows are proposer preferences

## Defining windows

As an organiser, I want to define the windows a proposer can say they are
available in, so that I learn when people can run their sessions.

As an organiser, I want every window offered to every proposer regardless
of kind, so that I do not maintain a per-kind list.

As an organiser, I want the notion of a "required" window gone, so that
nobody wonders what a mandatory availability could mean.

## Proposing

As a proposer, I want to pick the windows I am available in when the event
offers more than one, so that the organiser schedules me at a time I can
make.

As a proposer, I want the availability question skipped when the event
offers one window or none, so that I am not asked a question with no
choice.

## Accepting

As an organiser, I want accepting a proposal to change only its status, so
that accepting and scheduling are two separate decisions.

As an organiser, I want scheduling to happen only on the timetable, so that
there is one place that puts sessions in rooms and times.

As an organiser, I want a session I place to count as schedule-confirmed
only when I have switched automatic confirmation on for the event, so that
one setting decides what a placement means everywhere.

As an organiser, I want a proposer's availability shown when I place their
session, so that I honour their preference without looking it up.

## What it touches

- Migration: drop `TimeSlotRequirement`. The overlap constraint stays until
  03 — while the timetable still derives its grid, its capacity and its
  placement gate from slots, overlapping windows would double-count
  capacity and widen the grid.
- Wizard: `get_timeslot_requirements` becomes "list event slots"; the step
  renders when there are two or more. The kind settings page loses its
  time-slot block.
- Delete the legacy accept page: `ProposalAcceptPageView`,
  `chronology/accept_proposal.html`, `create_proposal_acceptance_form`,
  `ProposalAcceptanceService.accept_session` and its context DTO,
  `panel:proposal-accept`. The accept action in `proposal-actions.html`
  becomes the status flip; placement stays with the timetable.
- That deletion is also a decision about confirmation, and it is deliberate:
  the accept page wrote `session_confirmed=True` unconditionally, while the
  timetable writes `event.auto_confirm_sessions and not is_move`. After it
  goes, `auto_confirm_sessions` is the only thing that decides, so an
  organiser who accepted-with-placement and never set the flag sees those
  sessions as unconfirmed in the confirmation sweep and on facilitator
  cards. Events relying on the old behaviour switch the flag on; the release
  notes say so.
