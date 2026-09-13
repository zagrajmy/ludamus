# Session buckets replace the status enum

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
  track. Status is never consulted.

## What's wrong because of it

**The enum is a bucket pretending to be a state machine.** Any status may
move to any other. The only real rule is "placed ⇒ accepted". Yet the four
names are hard-coded into the enum, two badge templates, the filter select,
the proposal-detail button block, the confirmations grouping constants, and
the `count_by_track` aggregate. An organizer who wants a fifth step (say
"copy-edited") cannot have one.

**The UI derives a fifth status.** `_proposal_status_badge.html` renders
`accepted AND is_scheduled` as "Scheduled". The proposals filter select lists
"Scheduled" as an option next to real statuses, and
`ProposalPanelService.list_context` makes picking a real status *exclude*
placed sessions so the backlog looks right. Placement is a filter sitting in
a status control — the type error CLAUDE.md warns about. It also leaks:
`proposals.html` passes `is_scheduled=False` literally,
`facilitator-detail.html` passes nothing, so the same session badges
differently on three pages.

**"Confirmed" means three things.** `SessionParticipationStatus.CONFIRMED` is
a seat. `AgendaItem.session_confirmed` is the facilitator's agreement to a
slot. The confirmations tab calls the second one "confirmed program items".
Users read "confirmed" as "accepted". The field also lives on `AgendaItem`, so
every DTO that wants it joins through the agenda item and every write
(`assign_session`, `revert_change`, `accept_session`) re-decides the default —
and they disagree: `accept_session` hard-codes `True`, ignoring
`auto_confirm_sessions`.

**Two badge maps disagree.** `on_hold` is info-blue in
`_proposal_status_badge.html` and neutral-grey in
`confirmation-status-badge.html`. Neither is a tessera tag.

**`get_category_stats.accepted_count`** counts `~Q(status=pending)`, so on-hold
and rejected proposals inflate the CFP page's "accepted" figure.

## Shape of the fix

Three axes, three fields, one display component.

| Axis | Storage | Who sets it |
| --- | --- | --- |
| Bucket(s) | `Session.buckets` M2M → `SessionBucket` | organizer, freely |
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
  event          FK Event, related_name="session_buckets"
  name           CharField(255)
  slug           SlugField
  order          PositiveIntegerField(default=0)
  icon           CharField(50, blank)          # heroicons name, as SessionField.icon
  color          CharField(choices=BucketColor) # semantic token, see below
  can_be_planned BooleanField(default=False)
  Meta: ordering ["order", "name"]; unique (event, slug); unique (Lower(name), event)
```

- **Default bucket** is the one with the lowest `order`. New proposals, imports
  and restores land there. No `is_default` flag: one fewer field, and the list
  page says "first bucket receives new proposals". If an organizer sorts
  "Rejected" first they get what they asked for. A per-category default
  (nullable `ProposalCategory.default_bucket`, falling back to lowest order)
  is deliberately not built: category is already a filter on the inbox, and
  a bucket is a workflow step, not a kind. Add the FK the day a CFP needs a
  different first step.
- **`can_be_planned`** is a checkbox on the bucket form, next to icon and
  colour.
- **Colour** is a choice of semantic tokens (`success`, `info`, `warning`,
  `danger`, `neutral`, plus two or three accents), rendered through a class
  map. No hex input: nothing in the design system takes a free colour, dark
  mode needs a pair per colour, and a chip in `bg-warning-bg text-warning-text`
  is already what the current badges do. The `KonwencikExportSettings` hex
  colours are an export format, not UI.
- **Order** is a number field on the form and a column in the list. Drag
  reorder (the `SpaceReorderActionView` + `space-tree.ts` pattern) can come
  later if organizers ask.
- **Delete** is refused while any session sits in the bucket, and refused for
  the last bucket of an event. Both surface as a flash, matching
  `TrackDeleteActionView`.
- **Seeding.** Every event gets four buckets at creation and in the data
  migration, matching today's labels and `django.po` translations:

  | order | name (pl) | icon | color | can_be_planned |
  | --- | --- | --- | --- | --- |
  | 0 | Oczekujące | inbox | warning | no |
  | 1 | Zaakceptowane | check-circle | success | yes |
  | 2 | Rezerwa | pause-circle | info | no |
  | 3 | Odrzucone | x-circle | danger | no |

  Slugs stay `pending` / `accepted` / `on_hold` / `rejected` so the reverse
  migration can map back to the enum. Event creation seeds them through
  `gettext` under the request language; the migration seeds Polish, which is
  what production shows today.

### `Session.buckets`

Always an M2M. The single-bucket mode is a service rule, not a schema shape:
with `Event.multi_bucket_sessions` off, `set_buckets` replaces the set and
the UI is a kanban (one column per bucket, a card sits in exactly one); with
it on, `toggle_bucket` adds or removes and the UI is a checklist. A schema
with both an FK and an M2M would need every reader to check the flag before
picking a column. One M2M means one query path and turning the setting on
later is free.

Turning the setting **off** while sessions hold several buckets: refuse with
a message naming the count, same as bucket delete. Offer nothing cleverer
until someone needs it.

### The one invariant

> A placed session holds at least one bucket with `can_be_planned`.

This replaces both `SESSION_NOT_ACCEPTED` and `ProposalScheduledError`:

- `assign_session` (and `revert_change` for an UNASSIGN) checks the session
  holds a plannable bucket; the rejection reason is renamed
  `SESSION_NOT_PLANNABLE`, the 422 text becomes "Only sessions in a bucket
  marked as ready to plan can be placed on the schedule."
- `set_buckets` / `toggle_bucket` refuse to remove the last plannable bucket
  from a placed session (`SessionPlacedError`, same copy as today's
  `ProposalScheduledError`). Disabled buttons in `proposal-detail.html`
  mirror it as they do now.
- Unassign leaves buckets alone (as today). Soft-delete leaves buckets alone
  too — today it resets to `pending`, but a restored session reappearing
  unplaced in its plannable bucket is what the timetable's backlog pane is
  for, and one less write is one less rule to explain.
- Public visibility stays "placed AND public track". The invariant makes
  "placed" imply "plannable", so the public page needs no bucket join.

Bucket `can_be_planned` never changes a session's placement: unticking it
on a bucket that holds placed sessions is refused with the count, like delete.

### `Session.schedule_confirmed`

Move the bool from `AgendaItem` to `Session`, renamed. Semantics as before,
made explicit in one place:

- `assign_session`: `event.auto_confirm_sessions and not is_move`.
- `unassign_session`, `revert_change`: set `False`.
- `accept_session`: use `event.auto_confirm_sessions` — the current
  hard-coded `True` is the bug that lets placing stand in for confirming.
- `SessionConfirmationService.set_session_confirmed` and
  `EventConfirmationsService.set_confirmed` write it by session pk instead of
  agenda-item pk; the `agenda_item_pk` parameters and
  `ConfirmationSessionDTO.agenda_item_pk` become `session_pk`. A session that
  is not placed cannot be confirmed (service rule, 422).

Labels: "Schedule confirmed" / pl "Termin potwierdzony". The settings heading
"Schedule confirmation" already exists; the `auto_confirm_sessions` flag keeps
its name.

A nullable `schedule_confirmed_at` timestamp instead of a bool would give the
confirmations dashboard "when" for free. Not doing it: every reader today is a
`Count(filter=Q(...=True))` and nothing asks for the date.

### One display component

`components/session_state.html` (an include, like the badges it replaces,
until a third page needs Python logic) takes `buckets`, `is_scheduled`,
`schedule_confirmed` and renders three slots:

1. **Bucket chips** — icon + name in the bucket's colour. In multi-bucket
   mode with more than one bucket, icons only, each with `title`/`aria-label`.
2. **Planned** — calendar icon, muted when unplaced, `aria-label`
   "On the timetable" / "Not on the timetable".
3. **Schedule confirmed** — check-badge icon, success when confirmed, hidden
   when unplaced (nothing to confirm).

`compact=True` drops the bucket names. It replaces `_proposal_status_badge.html`,
`parts/confirmation-status-badge.html`, the lock icon on
`timetable-session-card.html`, and the confirmed line on
`timetable-session-detail.html`. Consumers: proposals table cell, proposal
detail, facilitator detail, deleted proposals, timetable card and detail
pane, confirmation cards, timetable overview pills, MCP `list_sessions`.

### Filters

Three controls, one kind each:

- **Bucket** — select (single mode) or multi-select (multi mode), options
  from the event's buckets, plus "All".
- **Planned** — `all` / `planned` / `unplanned`.
- **Schedule confirmed** — `all` / `confirmed` / `unconfirmed`.

The default view stays the inbox: default bucket, unplanned. The
"Scheduled" pseudo-status, `SCHEDULED_FILTER`, and the
real-status-excludes-placed rule in `ProposalPanelService.list_context` go.
`SessionListFilters.status` becomes `bucket_pks: list[int]`, `scheduled`
stays, `confirmed: bool | None` is new.

### Kanban and checklist

Kanban (single mode): columns are buckets in `order`, cards are the same
`_proposal_cell.html` rows, a card carries a "Move to…" select posting to
the existing bulk endpoint with one id. Drag between columns is a later
addition; the select makes the page keyboard-complete on day one.

Checklist (multi mode): proposal detail shows one checkbox per bucket,
`hx-post` on change, replacing the four action buttons. The list page gets
the multi-select filter.

The list/table view stays for both modes. The kanban is a `view=board`
switcher segment next to the table, in the sense of the CLAUDE.md rule: it
switches layout of the same set.

### Things that change shape

- `SessionStatus` enum is deleted. `Session.status` column dropped by the
  data migration after backfill. `AgendaItemDTO.session_status` (never read)
  goes with it.
- `SessionDTO.status`, `SessionListItemDTO.status` → `buckets:
  list[SessionBucketDTO]` (pk, name, slug, icon, color, can_be_planned).
- `ProposalStatusService.mark_*` → `SessionBucketService.set_buckets` /
  `toggle_bucket`; the four action views collapse to one
  `ProposalBucketActionView` taking `bucket` (and `on` for multi mode); bulk
  view likewise.
- `create_accepted_session` (MCP) → `create_session(bucket_slug=None)`
  defaulting to the first plannable bucket, since that is what the callers
  mean.
- `count_by_track` / `TrackProgressDTO` / `timetable-overview.html` pills:
  counts per bucket in bucket order, plus planned. The progress
  denominator today is the "active pool" (`pending + accepted`); it becomes
  **sessions in the default bucket or any plannable bucket**. That is the
  same set for the seeded buckets and the only nuance the redesign
  hard-codes; say so in the PR.
- `specs/confirmations.py` (`SCHEDULED_STATUS`, `STATUS_ORDER`,
  `COUNTED_UNPLACED`) is deleted. Confirmation facilitator cards list placed
  sessions as rows, and unplaced sessions as rows with their bucket chips
  instead of a status group. `unplaced_count` / `pending_count` roll-ups go;
  the chips carry the information.
- `get_category_stats.accepted_count` counts sessions in plannable buckets.
- Django admin: `SessionBucket` registered, `Session.list_filter` by
  `buckets`.
- `docs/agents/architecture.md`: add `SessionBucket` to the `event` noun's
  model row.

## Steps

One feature file per step, under `docs/features/drafts/chronology/panel/`.
Each step is demoable through the UI. Steps 1 and 3 change a column that
running code writes, so each is two releases: **expand** (add the new
field, backfill, switch every read and write to it) and **contract** (re-run
the backfill for rows written during the rollout, drop the old field). The
expand release leaves the old column in place with its default, so it can be
rolled back without losing data; the contract release's reverse migration
re-adds the column and maps it back by slug.

1. **Rename confirmed** — `schedule-confirmation.md`.
   - Expand: add `Session.schedule_confirmed`, backfill from
     `AgendaItem.session_confirmed`, rewire the two services, three writers,
     repo aggregates, DTOs, the two toggle views, templates and copy. Fix
     `accept_session` to honour `auto_confirm_sessions`.
   - Contract: re-backfill, drop `AgendaItem.session_confirmed`.
   Independent of buckets, smallest, fixes a live bug.
2. **Buckets exist** — `session-buckets.md`. `SessionBucket` model, seed
   migration for existing events, seeding on event create, panel CRUD page
   with sidebar entry `panel:session-buckets` under the proposals group,
   `active_nav` key, icon preview, order field, delete and un-flag guards.
   No session touches it yet. One release.
3. **Cutover** — `session-state.md`.
   - Expand: `Session.buckets` M2M, backfill from `status` by seeded slug,
     replace every read, write, guard, filter and badge with the bucket
     versions and the new state component, add the planned and confirmed
     filters. `status` stays in the schema with its default and is no longer
     written.
   - Contract: re-backfill any session without a bucket into the default
     bucket, drop `status`, delete `SessionStatus` and
     `AgendaItemDTO.session_status`.
   The expand release is the big PR; it is mechanical once steps 1 and 2
   are in.
4. **Multi-bucket** — `multi-bucket-sessions.md`. `Event.multi_bucket_sessions`
   on the general settings tab (same trace as `auto_confirm_sessions`),
   `toggle_bucket`, checklist on proposal detail, multi-select filter,
   off-switch guard. One release.
5. **Board view** — `proposals-board.md`. Kanban switcher segment on the
   proposals page with the "Move to…" select per card. One release.

## Testing

- `mills`: unit tests for `SessionBucketService` (set/toggle, last-plannable
  guard, delete guards, off-switch guard), the assign invariant, confirmed
  defaults on assign/move/unassign/accept.
- `links`: bucket repo, backfill and reverse migration tests (the
  `test_migration_0150_track_names.py` shape).
- `gates`: page tests for the CRUD pages and the action views with the
  `assert_login_required` / `assert_not_a_manager` / `assert_event_not_found`
  ladder and full `context_data`; foreign bucket pk → 404 with no write.
- `tests/e2e`: the state component's three slots on the proposals table,
  detail, and timetable card; the kanban move.
- Existing surface: 20 source files and 14 test files import
  `SessionStatus`; 23 test files touch `session_confirmed`.
