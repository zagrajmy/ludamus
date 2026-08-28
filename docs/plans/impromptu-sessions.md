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

**The per-category window is decorative.** `ProposalCategory.start_time` and
`end_time` are editable in the CFP panel and drawn as a badge by `cfp_status`,
but nothing reads them as a gate. The only gate is `Event.is_proposal_active`
on the model. So the field an organizer would naturally reach for to open a
category during the event does nothing.

**Placement refuses a pending session.** `TimetableService.assign_session`
calls `_require_accepted`, so the placement path an impromptu claim wants is
closed by design. Relaxing it globally is wrong — the guard is what stops the
builder from dragging an unreviewed proposal into a room.

**Nothing prevents a double booking.** `assign_session` locks the space and
then creates, but it never checks for an overlapping item; conflicts are
*detected* afterwards by `ConflictService` and shown to the organizer as
warnings. That is fine for one organizer dragging cards. It is not fine for
two people in a corridor claiming the same room at 14:00, which is the whole
failure mode of a walk-up flow.

**Rejecting a placed session raises.** `ProposalStatusService._set_status`
raises `ProposalScheduledError` for any non-ACCEPTED transition once an
`AgendaItem` exists, and the panel turns that into "remove it from the
timetable first". For an impromptu claim that is backwards: rejecting it is
precisely the request to free the slot.

**An impromptu proposal would be invisible to the organizer.**
`review_inbox_proposals` filters `agenda_item__isnull=True`, so a placed
proposal never reaches the review queue — deliberately, per the comment there.
And the panel proposal list treats scheduled as a pseudo-status: picking
`PENDING` sets `scheduled=False`, so a placed pending session is excluded from
that filter too. It would show only under "All" and "Scheduled". There is no
screen on which an organizer sees "someone just claimed a room, say yes or no".

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

## Shape of the fix

Four changes, no new page.

**The category window becomes the switch.** A category whose
`start_time`/`end_time` bracket now is open, whether or not the event's own
proposal window is. `is_proposal_active` stays what it is; the wizard gains a
second way in, scoped to the categories that are open on their own clock. This
is what an organizer flips at 13:50 to open the corridor.

**`Session.is_impromptu` marks the claim.** One boolean. It is the
discriminator for the organizer's queue, for the reject rule, and for the badge.
The alternative — inferring it from "PENDING and placed" — collides with
imported data, where a scheduled session commonly keeps PENDING; the
organizer's queue would then be the entire imported programme.

**The wizard swaps its time-slot step for a spot picker.** For an impromptu
category, "which slots would suit you" is the wrong question — the proposer is
picking a specific empty cell. The step lists free `(space, TimeSlot)` pairs:
slots that have not started yet, crossed with the leaf spaces of the
category's tracks, minus everything `list_overlapping_in_space` reports.
Spaces group under their parent, as everywhere else. A claim takes the whole
slot; sub-slot durations are a later problem.

**Placement gets its own door.** Extract the body of `assign_session` after
`_require_accepted` into a private placement helper, and give the impromptu
service a `claim_spot` that reuses it with a different set of guards: the space
must belong to the category's tracks, the claim must be a create rather than a
move, and — under the existing space lock — `list_overlapping_in_space` must
come back empty or the claim loses the race and the picker is re-rendered.
`assign_session` keeps `_require_accepted` untouched.

Approval then needs almost nothing. Accepting a placed pending session already
works — ACCEPTED is the one transition `_set_status` permits. Rejection is the
gap: when the session is impromptu, reject unassigns first and then rejects,
writing the usual `ScheduleChangeLog` row so it is revertible. The guard stays
for everything else. And the organizer finds them through a new option on the
proposal list's existing status filter, alongside the `SCHEDULED_FILTER`
pseudo-value that is already there — same list, narrowed, with the accept and
reject buttons the rows already carry.

## Steps

Each step is demoable end-to-end through the UI.

1. **Open a category on its own clock.** `is_proposal_active` gains a
   companion that asks whether any category window is open; `_get_event` and
   the event page's CTA accept either. The wizard offers only the open
   categories when the event window itself is shut. Nothing else changes — the
   proposal still lands unplaced in the review inbox. Demo: set a category's
   window to now, watch Propose light up on a closed event.

2. **Claim a spot.** `Session.is_impromptu` and `ProposalCategory.tracks`
   (m2m to `Track`, empty meaning every leaf space) with one reversible
   migration, a tracks field on the existing CFP category form, the spot-picker
   step replacing `timeslots` for impromptu categories, and `claim_spot` with
   its overlap re-check under the space lock. The impromptu path requires
   authentication. Submitting places the session and it appears on the
   programme badged as awaiting confirmation, driven by the `session_status`
   already on `AgendaItemDTO`. Demo: two browsers race for the same cell; one
   wins, the other is told the spot went and re-picks.

3. **Close the loop.** An "Impromptu" option on the panel proposal list's
   status filter, resolving to `is_impromptu=True, status=PENDING`, and
   rejection of an impromptu session unassigning before it rejects. Demo: claim
   a spot, reject it in the panel, watch the cell go free again in the picker.

## Not in scope

Notifications. There are none for proposal status changes today — accept and
reject only flash a message to the organizer doing it — and `Facilitator` has
no email field, so telling a walk-up their claim was accepted is its own piece
of work. It belongs with the notification engine epic (#617), not here.

Enrollment. During a live event the enrollment configs are normally closed, so
`is_enrollment_available` returns false and an impromptu session is walk-in.
Leave it alone.

Sub-slot durations, a sidebar badge counting waiting claims, and any affordance
on the public programme grid itself ("propose here" on an empty cell). The
event page CTA is the entry point for now.

## Open questions

The Polish term for an impromptu session. "punkt programu" is taken by session
and "przedział czasowy" by time slot; "zgłoszenie na żywo" is the current
suggestion for the proposer-facing copy and "na żywo" for the panel filter.

Whether an organizer wants a way to open the corridor without opening a
category — an event-level switch rather than per-category windows. The
per-category shape is what the existing fields imply, and it buys the track
scoping for free, so it is what this plan assumes.
