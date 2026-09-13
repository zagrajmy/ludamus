# CFP redux: kinds, windows, availability, and one set of personal data

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
validation (`PlacementRejection.OUTSIDE_TIME_SLOTS`), the timetable's day tabs
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
   `offer_claim_window`, and `SessionFieldRequirement`. Loses `description`,
   `start_time`, `end_time`, `PersonalDataFieldRequirement`,
   `TimeSlotRequirement`.

2. **`CallForProposals`** (new, mirrors `EnrollmentConfig`): `event` FK, many
   per event, `start_time`, `end_time`, `description`,
   `allow_anonymous_proposals`, M2M `kinds`. `description` is the text the
   wizard shows on its first page, moved from `EventProposalSettings`. Absorbs
   `Event.proposal_start_time`/`proposal_end_time`, `EventProposalSettings`,
   `apply_dates_to_categories`, and the `cfp_status` badge. Several may be
   open at once; the wizard offers the union of their kinds. Same pacts, mills,
   links, and four-URL panel shape as enrollment windows.

3. **`TimeSlot`** stays a proposer availability window and nothing else.
   No overlap constraint. The wizard offers every event slot and shows the
   step when the event has two or more.

**Personal data is per event.** `PersonalDataField` gains `is_required`; its
`order` starts being persisted. The requirement table goes. The wizard enforces
`is_required`; panel pages recording data on someone's behalf stay optional.
A field with stored values cannot be deleted.

**The timetable gets its shape from the event.** Days and the daily span come
from `Event.start_time`/`end_time` plus the existing `DayTurnover`. Placement
is bounded by event dates only. The overview shows hours, not a percentage:
full-day capacity on a multi-day event includes empty night hours, so a
percentage would read as a problem that is not one.

**Navigation.** Event settings gains a "Call for proposals" tab (windows
CRUD, replacing the "Proposals" tab) and a "Availability windows" tab (time
slots). The top-level "Call for Proposals" sidebar entry becomes "Session
configuration" with tabs Kinds, Personal data fields, Session fields, and
optionally Tracks.

## Steps

Each step is reachable through the UI on its own and leaves the previous
behaviour intact where it is not the subject.

### 1. Personal data per event

1. Migration: add `PersonalDataField.is_required` (default false), backfill
   from `PersonalDataFieldRequirement` with `any(is_required)` across
   categories and `order` from the max requirement order; drop the table.
2. `PersonalDataFieldForm` and the create/edit pages gain "Required" and
   order inputs; the per-category selects disappear. Same checkbox guard as
   before: a checkbox field is never required. The repository persists `order`.
3. The category settings page loses its "Host Data Fields" block.
4. `ProposeSessionService.get_personal_requirements` takes the event, not the
   category. `dynamic_fields.requirement_fields` pairs `(field,
   field.is_required)`. The wizard's personal step moves before the kind step.
5. Delete guard: refuse when `PersonalDataFieldValue` rows exist for the
   field; row-action reason text says so. `FieldUsageSummary` counts values,
   not categories.
6. Supersede `docs/plans/facilitator-field-configuration.md` (its step 1 is
   this change; its "third switch" is not needed).

### 2. TimeSlot reduced to availability

1. Migration: drop `TimeSlotRequirement`. Drop the overlap check in
   `TimeSlot.validate_unique`, `PanelTimeSlotsService`, and
   `TimeSlotValidationError.OVERLAPS_EXISTING_SLOT`.
2. Wizard: `get_timeslot_requirements` becomes "list event slots"; the step
   renders when there are two or more. The category settings page loses its
   time-slot block.
3. Timetable shape from the event: `slot_windows_by_local_date` and
   `_shared_day_span` take windows derived from `Event.start_time`/`end_time`
   and `DayTurnover`; `capacity_hours` uses the same windows;
   `build_heatmap` too. Remove `_require_placement_in_time_slots` and
   `PlacementRejection.OUTSIDE_TIME_SLOTS`; keep event-date bounds.
4. Overview page: drop `filled_pct` and the progress bar; keep hours to
   fill, scheduled hours, capacity hours, rooms. Empty-state copy no longer
   mentions time slots.
5. Delete the legacy accept page (`ProposalAcceptPageView`,
   `chronology/accept_proposal.html`, `create_proposal_acceptance_form`,
   `ProposalAcceptanceService.accept_session` and its context DTO,
   `panel:proposal-accept`). The accept action in `proposal-actions.html`
   becomes the status flip; placement stays with the timetable.
6. Move the time-slot pages under event settings: URL paths under
   `settings/availability/`, tab in `_event_settings_tabs.html`,
   `active_nav="settings"`. Copy: "Availability windows" / "przedziały
   czasowe". MCP tool descriptions updated to say availability.

### 3. Session kinds and CFP windows

1. Rename `ProposalCategory` to `SessionKind` across Python, DTOs, protocols,
   services, templates, and URL names (`panel:cfp*` becomes
   `panel:session-kinds*`); `db_table` unchanged. Repository methods and MCP
   tools follow (`list_session_kinds`, `create_session_kind`). Polish stays
   "rodzaj atrakcji" publicly, "rodzaj" in the panel.
2. Sidebar: "Call for Proposals" entry becomes "Session configuration"
   (`PanelNav` key `session-config`), tabs Kinds, Personal data fields,
   Session fields. Kind edit page keeps name, durations,
   participant bounds, waitlist mode, and the session-field requirements;
   the description input goes, the wizard's kind card shows the name only.
3. New `CallForProposals` model + migration. Data migration creates one
   window per event from `proposal_start_time`/`proposal_end_time` and
   `EventProposalSettings`, linked to all existing kinds; then drop those
   fields, the settings model, `SessionKind.start_time`/`end_time`/
   `description`, and `apply_dates_to_categories`.
4. Pacts/mills/links/inits mirror enrollment windows:
   `CallForProposalsData`/`DTO`, repository protocol, `CFPSettingsService`
   with `list_windows`/`read_window`/`create_window`/`update_window`/
   `delete_window`, period validation, transactional writes.
5. Event settings: "Proposals" tab becomes "Call for proposals" listing
   windows (Period, Kinds, Anonymous, Status) with create/edit/delete pages
   mirroring `enrollment-settings.html` and `enrollment-window-form.html`.
6. Wizard: one URL. `Event.is_proposal_active` becomes "any window open
   now"; the kind step lists the union of kinds across open windows; the
   description shown on the first page comes from the open windows. With one
   kind the step is skipped as today. Closed windows keep their kinds
   editable in the panel.
7. Public event page and MCP `list_proposal_categories` read kinds; nothing
   public reads a window except the wizard.

### 4. Optional: tracks under session configuration

Tracks are session attributes with managers and spaces. Moving them adds a
fourth tab and drops the "Tracks" sidebar entry from the schedule group. Do it
only if step 3's sidebar feels incomplete without it.

## Not in scope

Merging `PersonalDataField` and `SessionField` into one table. Per-kind
organizer permissions. Kind ordering. Per-room or per-day programme hours; the
event window plus `DayTurnover` is the only shape the timetable knows.

## Feature files

One file per shippable feature, 8 to 13 points each, in `cfp-redux/`.
Points: 1 is the smallest change through CI, tests, and deploy.

| File | Points | Depends on |
| --- | --- | --- |
| [01 Personal data asked once per event](cfp-redux/01-personal-data-per-event.md) | 13 | — |
| [02 Availability windows are proposer preferences](cfp-redux/02-availability-windows-as-preferences.md) | 8 | 01 |
| [03 Timetable shaped by the event](cfp-redux/03-timetable-shaped-by-event.md) | 10 | 02 |
| [04 Panel navigation](cfp-redux/04-panel-navigation.md) | 11 | 02 |
| [05 Session kinds](cfp-redux/05-session-kinds.md) | 13 | 04 |
| [06 Call for proposals windows](cfp-redux/06-call-for-proposals-windows.md) | 13 | 05 |
| [07 Proposing through open calls](cfp-redux/07-proposing-through-open-calls.md) | 8 | 06 |

Total 76 points. Files 03 and 04 are independent of each other.
