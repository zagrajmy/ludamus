# Panel proposal fixes — plan

Branch: `feat/panel-proposal-fixes` off `main`. One commit per step, each step
demoable in the UI. Verification for every step: `mise run check` and
`mise run test:py` pass; screenshots via `mise run shots` for UI steps.

## Step 1 — Agenda progress % counts pending + accepted

**Problem**: the Overview tab's per-track progress divides scheduled by
accepted only, so a track full of pending proposals shows 100 % done.

### Changes

- `mills/chronology.py` — `TimetableOverviewService.track_progress`: the
  denominator becomes sessions with status `PENDING` or `ACCEPTED` (on-hold and
  rejected excluded). Numerator stays "scheduled" (scheduled implies accepted).
- `pacts` `TrackProgressDTO`: rename `accepted_count` → `planned_count`.
- `templates/panel/timetable-overview.html`: update the count label.
- i18n: update the pl catalog if the label string changes.

**Tests**: unit tests for `track_progress` — pending counted in denominator,
on-hold/rejected excluded.

## Step 2 — Accept and bulk accept from the proposals list

**Problem**: accepting proposals requires opening each detail page; with
hundreds of pending proposals triage is impractical.

### Changes

- `mills/chronology.py` — `ProposalStatusService.bulk_accept(*, event_pk,
  session_pks)`: single transaction, per-session lock +
  `require_session_in_event`, sets status `ACCEPTED`. Accept is a legal
  transition from every status, so no per-row error branches.
- `gates/.../panel/views/proposals.py` — `ProposalBulkAcceptActionView`
  (POST only, next to the other status action views): reads `proposal_ids`,
  calls `request.services.proposal_status.bulk_accept` (the service is
  already exposed on `inits/services.py`; new views must not touch
  `request.di.uow`), success message with the count, redirects back to the
  list preserving the current filter query string.
- `panel/urls.py` — route `proposals/bulk-accept/`.
- `templates/panel/proposals.html` — leading checkbox column, select-all
  checkbox in the header, "Accept selected (N)" button above the table
  (disabled when nothing is selected; small inline script keeps the count).
- i18n: pl strings for the button, the success message, and the select-all
  label.

**Design notes** (product-design):

- No confirm step: accept is reversible (move back to pending exists), so a
  confirm dialog would be needless friction.
- Select-all selects the current page only (pagination is 50/page) — the
  button count makes the scope visible; no "select all 400" affordance in v1.
- Accessibility: the select-all checkbox and each row checkbox get an
  `sr-only`/`aria-label` name ("Select all on page" / "Select {title}").
- Success message includes the count ("Accepted N proposals"); with the
  default *pending* filter the accepted rows disappear from the list, which
  doubles as feedback.
- Rows already render a status badge, so mixed-status selections need no
  special UI — accepting an accepted proposal is a no-op.

**Tests**: unit test for `bulk_accept`; integration test for the view
(accepts selected, ignores ids from another event, `assert_response`).

## Step 3 — Duration select instead of ISO text input

**Problem**: organizers must type raw ISO-8601 durations (`PT1H30M`) in the
panel edit/create forms, while the CFP wizard already offers a select built
from the category's configured durations.

### Changes

- `gates/web/django/forms.py` — in `create_proposal_form`, replace the
  inherited `duration` CharField with `ChoiceField(required=False)`; the
  choices are passed in by the caller.
- `gates/.../panel/views/proposals.py` — edit and create views build choices
  from the union of all the event's categories' `durations`
  (`ProposalCategoryDTO.durations`), labelled with the existing
  `format_duration` helper, plus an empty option; the edit view injects the
  session's current stored value as an extra option when it is not in the
  configured list, so legacy/imported values survive an unrelated edit.
- `templates/panel/proposal-edit.html`, `proposal-create.html` — swap the text
  input for a select, same markup pattern as the category select (the form is
  hand-rolled today; migrating it wholesale to `tessera_field` is out of
  scope, noted as existing debt).
- Skipped: per-category JS filtering of options — flat union list for v1.

**Design notes** (product-design):

- The select must render whenever the union is non-empty **or** the session
  has a stored value — if the field were hidden while a value exists, the
  next save would post no `duration` and silently wipe it.
- Union empty and no stored value → render nothing (no single-option or
  empty-only select; duration simply isn't part of this event's model).
- Empty option labelled the same as the CFP wizard's (`---`), field stays
  optional.

**Tests**: integration test asserting rendered choices (configured + injected
legacy value) and that posting a configured duration saves.

## Step 4 — Show only category-relevant or filled session fields

**Problem**: edit and detail views render every event session field regardless
of the proposal's category, and every save stamps empty value rows onto all of
them.

Visible set = fields configured for the proposal's category (required or
optional, via
`request.di.uow.proposal_categories.get_session_field_requirements`) ∪ fields
with a truthy stored value. No category → only filled fields.

### Changes

- `gates/.../panel/views/proposals.py`:
  - `ProposalDetailPageView` — filter `read_field_values` rows to the visible
    set.
  - `ProposalEditPageView._get_session_fields` — filter the event field list
    the same way.
  - `ProposalEditPageView._collect_session_field_values` — write values only
    for the visible set, so hidden fields are not wiped to empty on save.

**Architecture note**: the visible-set rule stays in the view module (small
pure helper shared by detail/edit/save paths).
`get_session_field_requirements` is an existing repo method already used by
the panel (`cfp.py`), so no new `request.di.uow` surface is added; these
views are legacy-style pending the services migration, and moving the rule
into a mills service is deferred to that migration.

**Tests**: integration — required-but-empty shown; non-category-and-empty
hidden; non-category-but-filled shown; save round-trip proves hidden fields'
values survive.

**Edge case accepted**: changing the category on the edit form swaps the field
set only after save (no dynamic re-render).

## Step 5 — Facilitator picker: assigned + search-to-add

**Problem**: edit renders every event facilitator as a checkbox row (search
only hides rows); create renders the same full list with no search. With
hundreds of facilitators the wall of checkboxes is unusable and buries the
cards below it (this is how the Tracks card went unnoticed).

### Changes

- New shared include `templates/panel/_facilitator_picker.html`, used by both
  edit and create:
  - assigned facilitators render as visible checked rows (uncheck = remove);
  - unassigned rows are hidden until the search query matches, capped at ~20
    visible matches with a "refine your search" hint beyond the cap;
  - empty query → only assigned rows visible.
- Extend the existing inline filter script into the picker behaviour; POST
  contract (`facilitator_ids` checkboxes + `facilitators_submitted`) is
  unchanged, so no view/service/form changes.
- Skipped: server-side autocomplete endpoint — hidden DOM rows are cheap at
  this scale; revisit if events reach thousands of facilitators.

**Design notes** (product-design):

- Zero assigned: show a short hint under the search box ("No facilitators
  assigned yet — search to add them.") instead of an empty gap.
- Create view requires at least one facilitator (form-level validation
  already exists) — the picker must render that validation error and keep
  the user's selection on the invalid re-render.
- Search input gets a visible label or `aria-label`; existing
  "no matches" message stays; cap overflow shows "Showing first 20 matches —
  refine your search."
- Long display names wrap within the row rather than truncating (names are
  the only identifier shown).
- Polish copy: facilitator → "twórca programu" per the translation table.

**Tests**: existing integration tests keep passing (POST contract unchanged);
no new backend surface.

## Step 6 — Tracks section in the create view

**Problem**: tracks can be edited on an existing proposal but not set at
creation.

### Changes

- `templates/panel/proposal-create.html` — same tracks checkbox card as the
  edit view (`track_ids` + `tracks_submitted`).
- `gates/.../panel/views/proposals.py` — `ProposalCreatePageView`: pass
  tracks into context on GET/invalid-POST; on success collect submitted track
  ids (reuse the edit view's validation approach) and pass them as the
  existing `track_ids` parameter of `sessions.create` — the repo already
  supports it, so creation stays a single atomic call and no protocol or
  view-level second write is needed.

**Tests**: integration — create with tracks assigns them; create without the
section untouched.

## Step 7 — Wide-screen layout for the edit view

**Problem**: the edit form is a single `max-w-2xl` column; on large screens
most of the viewport is empty margin and the page scrolls forever.

### Changes

- `templates/panel/proposal-edit.html` — drop the form's `max-w-2xl`; wrap the
  cards in `grid grid-cols-1 xl:grid-cols-3 gap-6 items-start`; Session
  Details + Session Fields cards in an `xl:col-span-2` wrapper (left, wide),
  Facilitators / Tracks / Preferred time slots / Personal data cards in the
  third column (right). Single DOM order, so mobile keeps today's column and
  tab order matches visual order.
- Rejected alternative: auto-filling card grid (`columns-*`) — unpredictable
  reading and tab order on a form.
- No sticky positioning on the side column in v1 — the Save button already
  lives in the page header and stays reachable.

**Tests**: none new (pure layout); screenshots at both desktop and narrow
width in the PR (`mise run shots`).

## Cross-cutting

- i18n: after adding strings, run makemessages/compilemessages via mise and
  fix both empty **and** fuzzy pl entries (Django ignores fuzzy).
- Every UI step: `mise run shots` screenshots for the PR description; check
  compact and wide viewports.
- Linters: `mise run lint:ast-grep` / `mise run lint:impeccable` as part of
  `mise run check`; no inline color vars; no raw noqa/ignore directives.
