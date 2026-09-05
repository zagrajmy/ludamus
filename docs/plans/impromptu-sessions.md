# Impromptu sessions: let walk-ups claim an empty programme slot

## Where we are

A proposal is a `Session` with `status=PENDING` and no `AgendaItem`; there is
no `Proposal` model. Placement is the separate `AgendaItem` row, a OneToOne to
`Session` carrying a space and concrete times. The wizard in
`gates/web/django/event/propose.py` walks category → personal → timeslots
→ details → review and produces exactly that: an unplaced PENDING session that
lands in `review_inbox_proposals`, which an organizer accepts, after which the
timetable builder drags it into a room.

That is a pre-event pipeline, and it closes when
`Event.proposal_start_time`/`proposal_end_time` closes. `_get_event` in
`propose.py` redirects on `event.is_proposal_active`, and the event page's
CTA is gated on the same flag. Once the event is running, nobody can put
anything into the programme except an organizer with the builder open.

Organizers were asked (Aug 2026) what they want here and answered: reuse the
empty spots in the programme spaces. An empty room at 14:00 is the resource
worth recovering, which is why this is a `Session` in a real `AgendaItem` and
not an `Encounter`. Encounter was the tempting alternative — it already has
create, edit, RSVP, QR and ICS — but it has no approval, no placement and no
conflict handling, and it recovers no rooms.

Most of the primitives are already there. `TimeSlot` gives each event a
non-overlapping time grid. `Track.spaces` already groups spaces, and the
timetable grid already walks the space tree and takes only leaves.
`AgendaItem` is indexed on `(space, start_time, end_time)` and
`list_overlapping_in_space` answers "is this cell taken" directly.
`ProposalCategory` already has `start_time`/`end_time` fields and a `cfp_status`
badge that renders them.

## What's missing, and what will break if we ignore it

**The per-category window is decorative, and the windows disagree on their
edges.** `ProposalCategory.start_time` and `end_time` are editable in the CFP
panel and drawn as a badge by `cfp_status`, but nothing reads them as a gate:
`get_categories` returns every category of the event unfiltered, so a category
whose window closed yesterday is still selectable as long as the event's window
is open. The only real gate is `Event.is_proposal_active` — spelled twice, with
two conventions: strictly at both ends on the model, inclusively and only on a
published event on the DTO. `cfp_status` is inclusive too, but falls through to
"Not set" for a category that has only an end time. So the field an organizer
would naturally reach for to open a category during the event does nothing, and
there is no single answer to "is this open right now".

**Placement refuses a pending session.** `TimetableService.assign_session`
calls `_require_accepted`, so the placement path an impromptu claim wants is
closed by design. Relaxing it globally is wrong — the guard is what stops the
builder from dragging an unreviewed proposal into a room.

**Three writers create `AgendaItem` rows, and none of them is race-safe.**
`assign_session` locks the space and then creates, but never checks for an
overlapping item. `ProposalAcceptanceService.accept_session` places on accept
with its own `list_overlapping_in_space` check but takes no lock, writes no
`ScheduleChangeLog` row and hardcodes `session_confirmed=True`.
`revert_change` restores a deleted placement with neither. Overlaps are
otherwise *detected* after the fact by `ConflictDetectionService` and drawn on
the grid as ERROR-severity `SPACE_OVERLAP` warnings an organizer is free to
leave standing. That is fine for one organizer dragging cards. It is not fine
for two people in a corridor claiming the same room at 14:00, which is the whole
failure mode of a walk-up flow.

**Rejecting a placed session raises, and the rejection cannot be undone.**
`ProposalStatusService._set_status` raises `ProposalScheduledError` for any
non-ACCEPTED transition once an `AgendaItem` exists, and the panel turns that
into "remove it from the timetable first". For an impromptu claim that is
backwards: rejecting it is precisely the request to free the slot. And
unassigning first does not make the pair revertible — a `ScheduleChangeLog`
row for `UNASSIGN` carries agenda coordinates and no status, and
`revert_change`'s `UNASSIGN` branch calls `_require_accepted`, so replaying it
over a rejected session raises rather than restoring anything.

**An impromptu proposal would be invisible to the organizer.**
`review_inbox_proposals` filters `agenda_item__isnull=True`, so a placed
proposal never reaches the review queue — deliberately, per the comment there.
And the panel proposal list decodes one `status` query value into a
`(status, scheduled)` pair, so picking `PENDING` forces `scheduled=False` and a
placed pending session drops out of that filter too. It would show only under
"All" and "Scheduled". There is no screen on which an organizer sees "someone
just claimed a room, say yes or no".

**It would be visible to everyone else immediately.**
`public_scheduled_sessions` filters on `agenda_item__isnull=False` and nothing
else — status is not consulted. A placed pending session is on the public
programme the moment it is placed. The `session_status` field already exists on
`AgendaItemDTO` and is read nowhere.

That last one is a fork, and the answer here is to accept it: the claim is
public the moment it is made, badged as awaiting confirmation. Hiding it until
approved would leave the slot looking free to the next person walking past,
which reintroduces exactly the race the locking is there to prevent. The cost
is unvetted text on the programme for as long as an organizer takes to look,
and the mitigation is that the impromptu path requires a logged-in author
regardless of `allow_anonymous_proposals`, so there is a name attached.

What that cost turns into, though, is the claim nobody can take back.
Notifications are out of scope, so an unanswered claim is the expected case
rather than the edge, and today only an organizer could undo one. A claim
therefore needs a bound and a way out of its own.

## Shape of the fix

**One canonical "can this visitor propose right now, and into what".** The gate
is `is_proposal_active`, and it is already read from views, mills, DTOs and five
templates under two boundary conventions. A companion flag beside it, `or`-ed at
every one of those call sites, doubles that to four properties
and spreads the decision over three layers. Instead the propose service answers
once: one computed field on the event DTO saying proposing is open, and the list
of categories it is open for. `_get_event`, the event page CTA and the wizard
read those and nothing else. The model property stays for the legacy callers
that still use it, but nothing new reads it.

**The category window becomes the switch, and it is authoritative — on a
published event.** `is_published` stays a hard gate above the windows: an
unpublished event has no public page to send a facilitator to, so nothing is
open on it whatever any category says. Category windows only decide *what* is
open on an already-published event. Within that, a category carrying its own
`start_time`/`end_time` is governed by them alone — open or shut — whether or
not the event's window is open; a category with neither falls back to the event
window; only a start means open from then on, only an end means open until
then. Both ends are inclusive, matching `cfp_status` and the
DTO, and the model property's strict comparison becomes inclusive so there is
one convention. This makes the badge honest, and it is what an organizer flips
at 13:50 to open the corridor. One-time cost: on an event that set a category
window decoratively and let it lapse, that category now closes. Check for such
categories before shipping step 1; the fix is to clear or extend the window.

**Overlap is fatal for a claim and a warning for an organizer.** A same-space
overlap is legal today — the builder lets an organizer place two cards in one
room and the grid reports it — so "no two items in the same space at once"
cannot be enforced for everyone. A Postgres `ExclusionConstraint` (`btree_gist`
over `space_id` and a time range) is the tempting shape, because it would bind
every writer including `accept_session` and collapse the three overlap
predicates the codebase carries into one. But it would turn a permitted
organizer action into an `IntegrityError`, it needs the overlapping rows
production already holds found and repaired before the migration can apply, and
it is invisible to the default test suite, which runs sqlite (`USE_POSTGRES`
defaults to false; only `mise run test:postgres` is real Postgres). Not worth it
for this feature.

So the rule is asymmetric, and stated rather than assumed. `claim_spot`
re-checks `list_overlapping_in_space` under the space lock and refuses.
`assign_session` is left alone: an organizer dragging a card onto a claimed cell
gets today's conflict warning, deliberately, because the human doing it can see
the claim card sitting there. `accept_session` gains the one thing it is
missing — it takes the space lock before its existing overlap check, so
accepting into a cell someone is claiming can no longer interleave. Its other
two gaps, no log row and `session_confirmed` hardcoded, are pre-existing and
stay out of scope.

**`Session.is_impromptu` marks the claim.** One boolean. It is the
discriminator for the organizer's queue, for the reject rule, and for the badge.
The alternative — inferring it from "PENDING and placed" — collides with
imported data, where a scheduled session commonly keeps PENDING; the
organizer's queue would then be the entire imported programme.

**The wizard gains a spot step; it does not swap one.** `_STEP_KEYS` is a fixed
tuple and `after()`/`at_or_before()` index into it, so a step that substitutes
for another breaks that arithmetic. `spot` joins the tuple after `timeslots`,
and the one predicate in `_Wizard.steps` shows exactly one of the two: for an
impromptu category "which slots would suit you" is the wrong question, because
the proposer is picking a specific empty cell. The step lists free
`(space, TimeSlot)` pairs — slots that have not started yet, crossed with the
event's leaf spaces, minus everything `list_overlapping_in_space` reports.
Spaces group under their parent, as everywhere else. A claim takes the whole
slot; sub-slot durations are a later problem. `propose.py` is already oversized,
so the step's view and form live in their own module beside `propose_forms.py`.

**Placement gets a door, not a back door.** `claim_spot` is a method on
`TimetableService`, not a private helper extracted out of `assign_session` for
another service to call. The body after `_require_accepted` owns the space lock,
the moved-from bookkeeping, the `auto_confirm_sessions` decision and the
`ScheduleChangeLog` write — that is `TimetableService`'s core, and reaching into
it from outside leaks the placement contract and weakens the "one guarded path
creates `AgendaItem`s" invariant a walk-up flow needs most. `claim_spot` states
its policy differences explicitly — the placeable status is PENDING rather than
ACCEPTED, an overlap under the lock is fatal rather than a warning, and the
placement is always a create and never a move — and shares the guards and the
log write with `assign_session` from inside the service.

**A claim is bounded and revocable.** One outstanding PENDING impromptu claim
per user per event; a second is refused, saying the first is still waiting. The
locks `claim_spot` inherits from `assign_session` are the wrong key for that
cap: one user claiming two different spaces at once takes two different space
locks, both count zero pending claims, and both commit. The counting therefore
needs a serialization on the pair, not on the space — a conditional
`UniqueConstraint` on `(event, presenter)` for rows that are PENDING, impromptu
and alive, matching the conditional-constraint style the models already use. It
states the invariant where a forgetful writer cannot miss it, and the count in
`claim_spot` becomes the friendly message rather than the enforcement, with the
`IntegrityError` mapped to the same one. The space lock stays exactly what it
is: overlap, and nothing else. Without the cap one logged-in account can walk
the picker and claim every free cell, each public on creation and each needing
its own organizer rejection, with nobody notified that it is happening.
And the claim's own author can withdraw it while it is PENDING — the same
operation as the organizer's rejection, with a different actor.

**Rejecting a claim is its own operation.** Not a branch in `_set_status`: that
is the single chokepoint for every status transition, and `is_impromptu` never
turns off, so an exception there would silently unplace a months-old impromptu
session swept up in a cleanup pass. Instead `TimetableService` gains
`release_claim` — one transaction that unassigns and then sets the status, in
that order, so the shared guard sees no `AgendaItem` and stays untouched. It
lives there because `unassign_session`, the space lock and the
`schedule_change_logs` repo are already there; `ProposalStatusService` holds no
log repo at all.

The revert story is a limitation, not a feature: the `UNASSIGN` row is written
for the audit trail, but it cannot restore a status, so revert is not offered
for it in the schedule-change UI and `revert_change` keeps raising as the
backstop. Recovering a mistakenly rejected claim is the ordinary path — put the
proposal back to PENDING or ACCEPTED and place it from the builder. Carrying
status on the log row is a schema change this feature does not need.

**The organizer finds claims by three filters, not a fourth pseudo-status.**
`ProposalListQuery.status` is one string decoded into a `(status, scheduled)`
pair, which is exactly why picking a real status silently forces
`scheduled=False`. Status, placement and origin are three orthogonal questions,
so they become three keys on the query: the existing `SCHEDULED_FILTER`
pseudo-value folds into the placement key, and impromptu is a value of origin.
"Waiting claims" is then status=PENDING plus origin=impromptu — same list,
narrowed, with the accept and reject buttons the rows already carry.

## Steps

Each step is demoable end-to-end through the UI.

1. **Open a category on its own clock.** The propose service computes whether
   proposing is open and which categories it is open for; `_get_event`, the
   event page CTA and the wizard read that. The computed field keeps
   `is_published` as a precondition, exactly as `EventDTO.is_proposal_active`
   does today, so an open category window cannot make proposing possible on an
   unpublished event. Under it the category window becomes authoritative and
   inclusive, the model property's comparison follows, and `cfp_status` stops
   answering "Not set" for a category that has only an end time. Nothing else
   changes — the proposal still lands unplaced in the review inbox. Demo: set
   a category's window to now and watch Propose light up on a closed event; set
   another's to yesterday and watch it leave the wizard.

2. **Claim a spot.** `Session.is_impromptu` with one reversible migration, the
   `spot` step in its own module, and `claim_spot` on `TimetableService` with
   its overlap re-check under the space lock — plus that same lock added to
   `accept_session`. The impromptu path requires authentication regardless of
   `allow_anonymous_proposals`. Demo: claim a cell and find the session on the
   public programme; two browsers race for it, one wins and the other is told
   the spot went and re-picks.

3. **Say what a pending claim is.** The awaiting-confirmation badge on the
   public programme, and the panel proposal list split into status, placement
   and origin filters. `is_impromptu` joins the `session_status` already on
   `AgendaItemDTO`, and the badge keys on both: PENDING alone would badge every
   imported session, which keeps PENDING while scheduled. Demo: the claim from
   step 2 reads as awaiting confirmation to a visitor and is one filter click
   away in the panel.

4. **Close the loop.** `release_claim` behind the panel's reject button for an
   impromptu session, and behind a withdraw button for the claim's own author
   while it is PENDING. It takes the acting user, and under the space lock
   re-reads the session and refuses anything that is not an impromptu PENDING
   claim, then admits only an organizer of the event or the claim's own
   presenter, raising the way `accept_session` raises
   `ProposalAcceptDeniedError`. Which button renders is not the check. Demo:
   claim a spot, reject it in the panel, watch the cell go free again in the
   picker; claim another and withdraw it yourself;
   a third account's withdraw of someone else's claim is refused.

5. **Bound it.** One outstanding PENDING impromptu claim per user per event,
   enforced by the conditional `UniqueConstraint` on `(event, presenter)` above
   with one reversible migration, named
   `session_one_pending_impromptu_claim_per_presenter`; `claim_spot` counts
   first for the message and wraps only the insert in a savepoint, mapping to
   that message just the violation of that constraint by name and re-raising
   every other `DatabaseConstraintError` — the transaction layer flattens
   foreign-key and `AgendaItem` failures into the same exception, and a blanket
   catch would report them as a second claim. The space lock keeps guarding
   overlap only. Demo: claim a spot, try to claim a second, get told the first
   is still waiting; two browsers racing a second claim both lose it.

## Not in scope

Notifications. There are none for proposal status changes today — accept and
reject only flash a message to the organizer doing it — and `Facilitator` has
no email field, so telling a walk-up their claim was accepted is its own piece
of work. It belongs with the notification engine epic (#617), not here.

Enrollment. During a live event the enrollment configs are normally closed, so
`is_enrollment_available` returns false and an impromptu session is walk-in.
Leave it alone.

Scoping a category to a subset of rooms. Nobody asked for it, and it costs an
m2m, a migration, a CFP form field, a join in the picker and an empty-means-all
sentinel — and a `tracks` field on `ProposalCategory` would sit one model away
from `Session.tracks`, which means something else entirely. The picker offers
the event's free leaf spaces.

A same-space exclusion constraint, for the reasons above; and carrying status on
`ScheduleChangeLog` so an impromptu rejection could be reverted.

Expiring a claim. Nothing sweeps a PENDING claim whose slot has come and gone —
it stays on the programme as history until an organizer rejects it. The picker
only offers slots that have not started, so a stale claim blocks nothing but the
grid cell it already occupied.

Splitting `mills/timetable.py`, which this feature grows further — issue #746
tracks it, and it is not a prerequisite.

Sub-slot durations, a sidebar badge counting waiting claims, and any affordance
on the public programme grid itself ("propose here" on an empty cell). The
event page CTA is the entry point for now.

## Open questions

The Polish term for an impromptu session. "punkt programu" is taken by session
and "przedział czasowy" by time slot; "zgłoszenie na żywo" is the current
suggestion for the proposer-facing copy and "na żywo" for the panel filter.

Whether an organizer wants a way to open the corridor without opening a
category — an event-level switch rather than per-category windows. The
per-category shape is what the existing fields imply, so it is what this plan
assumes.
