# CFP redux: kinds, windows, availability, and one set of personal data

The feature files in [`cfp-redux/`](cfp-redux/) are the plan of record: each
one is a shippable slice with its stories and what it touches. This file is
the analysis behind them and nothing else — it is not a second decomposition.

## Where we are

There is no `Proposal` model. A `Session` with status `PENDING` is the
proposal; it carries a nullable `category` FK to `ProposalCategory` and a
`time_slots` M2M to `TimeSlot`. Accepting a proposal is a status flip and
never touches either.

`ProposalCategory` does two jobs at once. As a **session kind** it labels
programme items (panel columns and filters, the public `__category` filter,
Konwencik's `type` column, MCP output) and owns waitlist behaviour
(`promotion_mode`, `offer_claim_window`). As **CFP configuration** it carries
`start_time`/`end_time`, `description`, participant bounds, and three
requirement tables: `PersonalDataFieldRequirement`, `SessionFieldRequirement`,
`TimeSlotRequirement`. Its dates gate nothing: the wizard checks
`Event.is_proposal_active`, driven by `Event.proposal_start_time` and
`proposal_end_time`, and the rest of the CFP window (description, anonymous
proposals) lives in `EventProposalSettings`. The organizer edits one CFP window
across three places and the category badge lies about it.

`TimeSlot` is documented in `mills/timeslots.py` as a proposer availability
window, but five timetable paths treat it as the programme's shape: placement
(which stretches the slots to fit since #1312), the timetable's day tabs
and vertical span, the occupancy heatmap, the capacity KPI, and the legacy
accept page, which copies a slot's edges into the agenda item. The model also
refuses overlapping slots, which stops kinds with different granularity from
coexisting. Enrollment and the public schedule never read it.

`PersonalDataFieldRequirement` is read by exactly one consumer, the proposal
wizard. Every facilitator panel page and the proposal-edit page pair every
event field with `is_required=False`. Two panel pages (category settings and
field create/edit) rewrite the same table from opposite directions with
different `order` rules. No test or fixture depends on a field being required
in one category and optional in another. `PersonalDataField.order` exists and
is never written.

The panel sidebar has a top-level "Call for Proposals" entry whose tabs are
Categories, Host Data Fields, Session Fields, Time Slots. Event settings has
a "Proposals" tab holding the real CFP window.

## What's wrong because of it

**Two concepts, one name.** "Proposal category" reads as CFP config in the
panel and as "rodzaj atrakcji" on the public side. Everything that only cares
about the kind (waitlists, exports, filters) drags CFP fields along.

**Requirements are keyed on the wrong axis.** Personal data is the same person
regardless of what they propose; the per-kind dimension is pure overhead and
a second writer. Time-slot "requirements" add an `is_required` that has no
meaning in the wizard.

**The timetable borrows its shape from proposer preferences.** An event with
no slots cannot place anything; an event whose slots do not cover the night
cannot schedule a late game.

**Navigation follows the code, not the organizer.** A CFP window is an event
setting like an enrollment window. Kinds and fields are session
configuration, needed whether or not a CFP is ever opened.

## Shape of the fix

Three concepts, each with one owner:

1. **`SessionKind`** (renamed `ProposalCategory`, table stays
   `proposal_category`). Keeps `name`, `slug`, `durations`,
   `min_participants_limit`, `max_participants_limit`, `promotion_mode`,
   `offer_claim_window`, and `SessionFieldRequirement`. Gains
   `accepts_proposals` (bool, default true). Loses `description`,
   `start_time`, `end_time`, `PersonalDataFieldRequirement`,
   `TimeSlotRequirement`.

2. **The call for proposals stays one switch per event.** Its period is
   `Event.proposal_start_time`/`proposal_end_time`, its text and anonymity
   setting stay in `EventProposalSettings`, and `Event.is_proposal_active`
   keeps its current meaning: both dates set and now between them, otherwise
   closed. What the call accepts is `SessionKind.accepts_proposals` — the
   realistic case is an event with a full programme of lectures that keeps
   taking workshop proposals, not two calls on different calendars.

   No `CallForProposals` model, no per-window kind M2M, no resolution policy
   for several open windows at once, no related-table lookup behind
   `is_proposal_active` (which a dozen public templates read). Two windows
   with different dates for different kinds, or a description authored per
   kind, are the two things this cannot express; neither has been asked for.
   The day one is, the switch becomes a table and the `accepts_proposals`
   flag moves onto it.

3. **`TimeSlot`** stays a proposer availability window and nothing else.
   No overlap constraint once the timetable stops reading slots. The wizard
   offers every event slot and shows the step when the event has two or more.

**Personal data is per event.** `PersonalDataField` gains `is_required`; its
`order` starts being persisted. The requirement table goes. The wizard enforces
`is_required`; panel pages recording data on someone's behalf stay optional.
A field with stored values cannot be deleted.

`SessionFieldRequirement`, the same shape, stays a join table: a session
question belongs to the kind of session being described — a workshop asks for
materials, a lecture does not — while personal data is the same person
whatever they propose. The join is the whole point in one case and pure
overhead in the other.

**The timetable gets its shape from the event.** Days and the daily span come
from `Event.start_time` and `Event.end_time` — the programme runs from the
first instant of the event to the last, and `DayTurnover` decides where one
day ends and the next begins. A placement past the event's dates widens them
(#1312); only the publication time bounds it. The
overview counts scheduled hours and rooms; capacity, hours-to-fill and the
filled percentage all go, because all three divide by a denominator that
includes every empty night hour.

Programme windows per day (a daytime lecture track and a night horror-film
track, in the same or different rooms) are a feature of their own, not a
number derivable from the event: filed as issue #1293.

**Navigation.** Event settings gains an "Availability windows" tab (time
slots) and keeps its CFP tab, renamed "Call for proposals". The top-level
"Call for Proposals" sidebar entry becomes "Session configuration" with tabs
Kinds, Personal data fields, Session fields, and optionally Tracks.

## Not in scope

Merging `PersonalDataField` and `SessionField` into one table. Per-kind
organizer permissions. Kind ordering. Several calls for proposals per event.
Per-room or per-day programme windows (issue #1293).

Splitting `links/db/django/models.py` (2066 lines) is worth doing and is
filed as issue #1294 — not as step zero of this plan, which would put an
import shuffle across the whole codebase in front of every behaviour change
here.

## Feature files

One file per shippable feature, in `cfp-redux/`. Points: 1 is the smallest
change through CI, tests, and deploy.

| File | Points | Depends on |
| --- | --- | --- |
| [01 Personal data asked once per event](cfp-redux/01-personal-data-per-event.md) | 13 | — |
| [02 Availability windows are proposer preferences](cfp-redux/02-availability-windows-as-preferences.md) | 8 | 01 |
| [03 Timetable shaped by the event](cfp-redux/03-timetable-shaped-by-event.md) | 10 | 02 |
| [04 Panel navigation](cfp-redux/04-panel-navigation.md) | 8 | 02 |
| [05 Session kinds](cfp-redux/05-session-kinds.md) | 16 | 04 |
| [06 Kinds a call accepts](cfp-redux/06-kinds-open-for-proposals.md) | 5 | 05 |

Total 60 points. Files 03 and 04 are independent of each other.

[`facilitator-field-configuration.md`](facilitator-field-configuration.md) is
superseded by 01: its step 1 is that change, and its "third switch" is not
needed once personal data is per event.
