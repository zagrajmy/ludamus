# Session buckets replace the status enum

**Nobody has asked for this.** No organizer has named a workflow step the
four statuses cannot express. It is written down so the shape is ready when
one does; until then it stays on the shelf. The bugs the current design
carries do not wait for it — they ship in
[session state fixes](session-state-fixes.md), which is independent of
everything here.

## Where we are

A session's state is three things wearing one word:

1. **Decision** — `Session.status`, a `SessionStatus` enum (`pending`,
   `accepted`, `on_hold`, `rejected`) in `pacts/legacy.py`. Written only by
   `ProposalStatusService` in `mills/chronology.py`, the public accept flow
   (`ProposalAcceptanceService.accept_session`), and creation paths that
   default to `pending` (propose wizard, panel create, CSV/Docs import) or to
   `accepted` (`create_accepted_session`, used by the MCP `create_session`
   tools).
2. **Placement** — whether an `AgendaItem` row exists. Nothing stores it; every
   consumer re-derives `agenda_item__isnull` or `hasattr(session,
   "agenda_item")`.
3. **Confirmation** — `AgendaItem.session_confirmed`. An organizer-ticked
   record that the facilitator agreed to the slot. Lost on unassign, reset on
   move, seeded from `Event.auto_confirm_sessions` on assign.

The three are orthogonal and the code says so in comments in three places
(`repositories/sessions.py` above `review_inbox_proposals`,
`specs/confirmations.py`, `event_presentation.py` at `is_unscheduled`). The
rules that bind them:

- `TimetableService.assign_session` requires `accepted`
  (`PlacementRejection.SESSION_NOT_ACCEPTED`).
- `ProposalStatusService._set_status` refuses any status but `accepted` while
  an `AgendaItem` exists (`ProposalScheduledError`).
- Unassign keeps `accepted`; soft-delete of a placed session unassigns *and*
  resets to `pending`.
- Public visibility (`public_scheduled_sessions`) is placement plus public
  track. Status is consulted in one other public place: the accept page
  refuses a proposal that is not `pending`
  (`gates/web/django/chronology/views.py`, `ProposalAcceptPageView._load`).
  That page goes — see "The public accept page" below.

## What a bug fix cannot cure

**The enum is a bucket pretending to be a state machine.** Any status may
move to any other. The only real rule is "placed ⇒ accepted". Yet the four
names are hard-coded into the enum, the badge template, the filter select,
the proposal-detail button block, the confirmations grouping constants,
`EventPanelSettings.proposal_columns` (the `"status"` column key) and the
`count_by_track` aggregate. An organizer who wants a fifth step (say
"copy-edited") cannot have one.

**"Confirmed" means three things.** `SessionParticipationStatus.CONFIRMED` is
a seat. `AgendaItem.session_confirmed` is the facilitator's agreement to a
slot. The confirmations tab calls the second one "confirmed program items".
Users read "confirmed" as "accepted". The field also lives on `AgendaItem`, so
every reader that has a session in hand has to join to the agenda item to
learn whether its schedule is confirmed.

## Shape of the fix

Three axes, three fields, one display component.

| Axis | Storage | Who sets it |
| --- | --- | --- |
| Bucket | `Session.bucket` FK → `SessionBucket`, mandatory | organizer, freely |
| Planned | `AgendaItem` exists (unchanged) | timetable |
| Schedule confirmed | `Session.schedule_confirmed` bool | organizer, after talking to the facilitator |

### `SessionBucket`

Per-event, organizer-owned. Copy the `Track` slice for layering
(`pacts/tracks.py` → `mills/tracks.py` → `TrackRepository` →
`chronology/panel/views/tracks.py` → `panel/tracks.html`), the `SessionField`
icon field with the `panel:icon-preview` HTMX preview, and the `DiscountRule`
plain `order` number field.

```text
SessionBucket
  event   FK Event, related_name="session_buckets"
  name    CharField(255)
  order   PositiveIntegerField(default=0)
  icon    CharField(50, blank)           # heroicons name, as SessionField.icon
  color   CharField(choices=BucketColor) # semantic token, see below
  Meta: ordering ["order", "name"]; unique (Lower(name), event)
```

**Order carries the workflow.** Two rules, no flags:

- The **lowest-order** bucket is the inbox. New proposals, imports and
  restores land there. Its sessions are the unprocessed ones.
- The **highest-order** bucket is the one whose sessions may go on the
  timetable.

An event with one bucket therefore has an inbox that is also ready to plan:
a programme needing no acceptance step is plannable the moment it is
proposed, and nothing counts as unprocessed. No `is_default` flag, no
`can_be_planned` checkbox, no third state to explain — the list page says
which end is which, and reordering is how an organizer changes it.

A per-category inbox (nullable `ProposalCategory.default_bucket`) is
deliberately not built: category is already a filter on the inbox, and a
bucket is a workflow step, not a kind. Add the FK the day a CFP needs a
different first step.

- **Colour** is a choice of semantic tokens (`success`, `info`, `warning`,
  `danger`, `neutral`, plus two or three accents), rendered through a class
  map. No hex input: nothing in the design system takes a free colour, dark
  mode needs a pair per colour, and a chip in `bg-warning-bg text-warning-text`
  is already what the current badges do. The `KonwencikExportSettings` hex
  colours are an export format, not UI.
- **Order** is a number field on the form and a column in the list. Drag
  reorder (the `SpaceReorderActionView` + `space-tree.ts` pattern) can come
  later if organizers ask.
- **Address** is the pk, everywhere: `<int:pk>` in the panel URLs (as
  `cfp/time-slots/` and `discounts/` already do), `bucket_pk` in the list
  filter, `bucket_id` on the MCP surface. No slug, so renaming a bucket is
  just a rename and nothing carries a stale label. The reverse migration
  maps back to the enum by order position (0 → pending, last → accepted,
  anything else → pending), which is exact for an untouched seeded set and
  best-effort for a workflow the organizer has already rebuilt.
- **Guards**, each a flash matching `TrackDeleteActionView`:
  - delete is refused while any session sits in the bucket;
  - delete is refused for the last bucket of an event;
  - a reorder is refused when it would leave a placed session outside the
    highest-order bucket, naming the count. (This replaces the un-flag
    guard: with plannability derived from order, reordering is the only way
    to take it away.)
- **Seeding.** Every event gets four buckets at creation and in the data
  migration, matching today's labels and `django.po` translations. Accepted
  sorts last because the last bucket is the plannable one:

  | order | name (pl) | icon | color |
  | --- | --- | --- | --- |
  | 0 | Oczekujące | inbox | warning |
  | 1 | Rezerwa | pause-circle | info |
  | 2 | Odrzucone | x-circle | danger |
  | 3 | Zaakceptowane | check-circle | success |

  Both seed paths write these Polish literals. Event creation does not run
  them through `gettext`: `pl` and `en` are both configured, so a bucket
  seeded under an English UI would otherwise stay English on Polish pages,
  and two events would disagree on the name of the same workflow step. Nor
  are they translation keys — the feature file makes a bucket name
  renameable organizer text, and no key survives a rename.

  **Known gap:** creation paths that build an `Event` without going through
  the create flow — admin, factories, fixtures — get no buckets, exactly as
  they get no `EventSettings`, `EventPanelSettings` or
  `EventProposalSettings` today. With a mandatory FK a bucketless event
  cannot take a session at all, so this plan does not paper over it here;
  seeded/templated/cloned event configuration is its own feature and fixes
  every one of them at once.

### `Session.bucket`

One FK, `on_delete=PROTECT`, not nullable. A session is in exactly one
bucket, always:

- the delete guard is a database constraint rather than a service rule;
- "placed ⇒ plannable" is one join and needs no `distinct()`;
- counts per bucket are a plain `GROUP BY`;
- a session with no bucket — invisible to the inbox, to every filter and to
  every board column — is unrepresentable, so nothing has to sweep for one.

A session in several buckets (a checklist rather than a pipeline) is not
built. Should one ever be asked for, it arrives as its own plan carrying its
own FK → M2M migration, and pays for the reader cost it adds.

Both paths that take a caller-supplied `bucket_id` —
`SessionRepository.create` and `SessionBucketService.set_bucket` — resolve
it within the session's own event before any write; a bucket pk from
another event 404/422s and writes nothing. The scoping lives in the
service, not the view, and a `mills` test covers it, so the guard holds
for the MCP surface and every non-page caller too, not only the panel
pages the `gates` tests exercise.

`SessionRepository.create` resolves the bucket: callers may pass
`bucket_id`, and when they don't, the repository writes the event's
lowest-order bucket. That is the single owner of the default, so none of the
five creation paths (propose wizard, panel create, import engine, MCP
`create_session`, restore) can forget it. `SessionData.status` becomes an
optional `bucket_id` key.

The MCP surface uses that same default. `create_accepted_session` becomes
`create_session(bucket_id=None)` landing in the inbox like everything else;
a caller building finished programme names the plannable bucket it read from
`list_buckets`. One default in the system, not two.

### The one invariant

> A placed session sits in the plannable (highest-order) bucket.

This replaces both `SESSION_NOT_ACCEPTED` and `ProposalScheduledError`:

- `assign_session` (and `revert_change` for an UNASSIGN) checks the session's
  bucket is the plannable one; the rejection reason is renamed
  `SESSION_NOT_PLANNABLE`, the 422 text becomes "Only sessions in the last
  bucket can be placed on the schedule."
- `set_bucket` refuses to move a placed session out of the plannable bucket
  (`SessionPlacedError`, same copy as today's `ProposalScheduledError`).
  Disabled buttons in `proposal-detail.html` mirror it as they do now.
- The bucket reorder guard above keeps the invariant true when the order,
  rather than the session, is what moves.
- Unassign leaves the bucket alone (as today). Soft-delete leaves it alone
  too — today it resets to `pending`, but a restored session reappearing
  unplaced in its bucket is what the timetable's backlog pane is for, and one
  less write is one less rule to explain.
- Public visibility stays "placed AND public track". The invariant makes
  "placed" imply "plannable", so the public page needs no bucket join.

### The public accept page

`ProposalAcceptPageView` (`gates/web/django/chronology/views.py`,
`chronology/accept_proposal.html`, `ProposalAcceptanceService`) is deleted in
this redesign, together with its `status != PENDING` guard — the one public
read of the enum. Accepting a proposal into a slot is panel work and the
panel does it; keeping a second acceptance path would mean teaching it the
bucket rules too. Its route, template, service, protocol and DI entry go with
it.

### `Session.schedule_confirmed`

Move the bool from `AgendaItem` to `Session`, renamed. It is a deliberate
denormalization: a session then carries everything its state display needs,
and no reader that holds a session has to fetch the agenda item to find out
whether the schedule is confirmed. Semantics as before, made explicit in one
place:

- `assign_session`: `event.auto_confirm_sessions and not is_move`.
- `unassign_session`, `revert_change`: set `False`.
- `SessionConfirmationService.set_session_confirmed` and
  `EventConfirmationsService.set_confirmed` write it by session pk instead of
  agenda-item pk; the `agenda_item_pk` parameters and
  `ConfirmationSessionDTO.agenda_item_pk` become `session_pk`. Both services
  keep the event and facilitator scoping they do today. A session that is not
  placed cannot be confirmed (service rule, 422).

Labels: "Schedule confirmed" / pl "Termin potwierdzony". The settings heading
"Schedule confirmation" already exists; the `auto_confirm_sessions` flag keeps
its name.

A nullable `schedule_confirmed_at` timestamp instead of a bool would give the
confirmations dashboard "when" for free. Not doing it: every reader today is a
`Count(filter=Q(...=True))` and nothing asks for the date.

### One display component

A tessera tag, `{% session_state session %}`
(`adapters/web/django/templatetags/tessera/session_state.py`), taking the
session DTO and nothing else. Nine call sites is well past the bar for a tag,
and one argument means the contract is checked in Python instead of by
grepping templates for a slot a caller forgot — which is exactly how the
current badge ended up rendering the same session three ways.

It reads `bucket`, `is_scheduled` and `schedule_confirmed` off the DTO and
renders three slots:

1. **Bucket chip** — icon + name in the bucket's colour.
2. **Planned** — calendar icon, muted when unplaced, `aria-label`
   "On the timetable" / "Not on the timetable".
3. **Schedule confirmed** — check-badge icon, success when confirmed, hidden
   when unplaced (nothing to confirm).

`compact=True` drops the bucket name. It replaces
`_proposal_status_badge.html`, the lock icon on
`timetable-session-card.html`, and the confirmed line on
`timetable-session-detail.html`. Consumers: proposals table cell, proposal
detail, facilitator detail, deleted proposals, timetable card and detail
pane, confirmation cards, timetable overview pills. MCP `list_sessions`
renders no template; it reads `SessionBucketDTO` off the session DTO.

### Filters

Three controls, one kind each:

- **Bucket** — select, options from the event's buckets in order, plus "All".
- **Planned** — `all` / `planned` / `unplanned`.
- **Schedule confirmed** — `all` / `confirmed` / `unconfirmed`.

The default view stays the inbox: lowest-order bucket, unplanned.
`SessionListFilters.status` becomes `bucket_pk: int | None`; `scheduled` and
`confirmed: bool | None` are the other two. The "Scheduled" pseudo-status and
the real-status-excludes-placed rule are already gone by then — they are
defect 5 of [session state fixes](session-state-fixes.md).

### Board

Columns are the event's buckets in `order`, cards are the same
`_proposal_cell.html` rows, a card carries a "Move to…" select posting to the
existing bulk endpoint with one id. One bucket per session means one card in
one column, so a move is a move and a column count is a count. Drag between
columns is a later addition; the select makes the page keyboard-complete on
day one. An empty column says it is empty.

The board is a `view=board` switcher segment next to the table, in the sense
of the CLAUDE.md rule: it switches layout of the same set. The last view used
is remembered per event in `EventPanelSettings`, which already stores that
page's columns.

### Things that change shape

- `SessionStatus` enum is deleted. `Session.status` column dropped after the
  cutover. `AgendaItemDTO.session_status` (never read) goes with it.
- `SessionDTO.status`, `SessionListItemDTO.status` → `bucket:
  SessionBucketDTO` (pk, name, icon, color, order, is_plannable).
- `ProposalStatusService.mark_*` → `SessionBucketService.set_bucket`; the four
  action views collapse to one `ProposalBucketActionView` taking `bucket`;
  bulk view likewise.
- `EventPanelSettings.proposal_columns`: the `"status"` key becomes
  `"bucket"`, migrated in place.
- `count_by_track` / `TrackProgressDTO` / `timetable-overview.html` pills:
  counts per bucket in bucket order, plus planned. The progress denominator
  today is the "active pool" (`pending + accepted`); it becomes **sessions in
  the plannable bucket**, which is the same set for the seeded buckets and
  needs no notion of which bucket is the inbox.
- `review_inbox_proposals` (`repositories/sessions.py`, the public event
  page's review block, and `own_pending_proposals` built on it): today
  `status=PENDING AND agenda_item__isnull`. It becomes **unplaced sessions in
  the lowest-order bucket** — the unprocessed ones. A one-bucket event is no
  exception: inbox and plannable coincide, and the block lists the unplaced
  sessions sitting there, which is what `session-state.md` asks for —
  "the sessions sitting in the inbox that are not yet on the timetable".
- `specs/confirmations.py` (`SCHEDULED_STATUS`, `STATUS_ORDER`,
  `COUNTED_UNPLACED`) is deleted. Confirmation facilitator cards list placed
  sessions as rows, and unplaced sessions as rows with their bucket chip
  instead of a status group. `ConfirmationFacilitatorGroupDTO.unplaced_count`
  and `.pending_count` (`mills/event.py`) become one count per bucket: with
  organizer-defined buckets "pending" is no longer a thing the code can name,
  and the bucket an organizer named is more informative than a roll-up.
- `get_category_stats.accepted_count` counts sessions in the plannable
  bucket. (Its `~Q(pending)` bug is fixed before this, in the fixes plan.)
- Django admin: `SessionBucket` registered, `Session.list_filter` by
  `bucket`.
- `docs/agents/architecture.md`: add `SessionBucket` to the `event` noun's
  model row.

## Steps

One feature file per step, under `docs/features/drafts/chronology/panel/`.
Each step is demoable through the UI on its own page.

Two columns move under running code (`session_confirmed`, `status`). Those
releases **write both** the old and the new column for as long as the old one
exists, so any release in the sequence can be rolled back and read current
data. Everything else is one release with a reversible migration, the shape
migration 0150 already has.

1. **Rename confirmed** — `schedule-confirmation.md`.
   1. Add `Session.schedule_confirmed`, backfill from
      `AgendaItem.session_confirmed`, write both columns everywhere the old
      one is written.
   2. Switch every read to the new column: repo aggregates, DTOs, the two
      confirmation services (`agenda_item_pk` → `session_pk`), the two toggle
      views, templates and copy.
   3. Stop writing `AgendaItem.session_confirmed`, re-backfill, drop it.

   Independent of buckets.
2. **Buckets exist** — `session-buckets.md`. `SessionBucket` model, seed
   migration for existing events, seeding on event create, panel CRUD page
   with sidebar entry `panel:session-buckets` under the proposals group,
   `active_nav` key, icon preview, order field, delete and reorder guards. No
   session touches it yet. One release.
3. **Cutover** — `session-state.md`, one release per surface. Every release
   keeps writing `status` alongside the bucket, and every surface not yet
   moved keeps reading `status`, so each one is demoable and revertible on
   its own:
   1. `Session.bucket` FK, backfill from `status` onto the seeded buckets,
      `SessionBucketService.set_bucket`, dual writes. Nothing reads the
      bucket yet. The backfill keys off the seeded rows by pk, not by
      position: step 2 ships bucket CRUD with no session referencing a
      bucket, so the "refused while sessions sit in it" guard is inert and
      an organizer can freely reorder or delete a seeded bucket before this
      release lands. Any status whose seeded bucket is gone falls back to
      the event's lowest-order bucket.
   2. Proposals list and detail: the `session_state` tag, the bucket action
      and bulk-move views, the three filters, the `proposal_columns` key.
   3. Timetable: the assign invariant and `SESSION_NOT_PLANNABLE`, session
      card and detail pane, overview pills and `count_by_track`.
   4. Confirmations: per-bucket counts, bucket chips on facilitator cards,
      `specs/confirmations.py` deleted.
   5. The rest: CFP `accepted_count`, MCP `create_session` / `list_sessions`,
      Django admin, the public event page's review block, and deletion of the
      public accept page.
   6. Contract: stop writing `status`, re-backfill anything written during
      the sequence, drop the column, delete `SessionStatus` and
      `AgendaItemDTO.session_status`.
4. **Board view** — `proposals-board.md`. Kanban switcher segment on the
   proposals page, "Move to…" select per card, empty-column message, last
   view remembered in `EventPanelSettings`. One release.

## Testing

- `mills`: unit tests for `SessionBucketService.set_bucket` (placed-session
  guard), the assign invariant, the reorder guard, the bucket delete guards,
  and the confirmed defaults on assign/move/unassign.
- `links`: bucket repo; `SessionRepository.create` defaulting to the
  lowest-order bucket, including when it is not the plannable one; backfill
  and reverse migration tests (the `test_migration_0150_track_names.py`
  shape).
- `gates`: page tests for the CRUD pages and the action views with the
  `assert_login_required` / `assert_not_a_manager` / `assert_event_not_found`
  ladder and full `context_data`; foreign bucket pk → 404 with no write. The
  existing foreign-event and foreign-facilitator confirmation tests post
  `agenda_item_pk` today and must be rewired to post `session_pk` while
  still asserting the same 404 and no write.
- `tests/e2e`: the state tag's three slots on the proposals table, detail,
  and timetable card; the board move.
- Existing surface: 20 source files and 14 test files import
  `SessionStatus`; 23 test files touch `session_confirmed`.
