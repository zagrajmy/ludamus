# Plan: Proposal CRUD in panel + edit-history audit trail

Two related but separable workstreams:

1. **Close CRUD gaps** in the panel proposal-edit surface — make every
   `Session` and `Facilitator` field that an organizer should be able to
   touch reachable from a form, and introduce the missing status
   transitions (accepted / on hold / reserve list). No-delete is an explicit
   policy.
2. **Change history** for `Session` and `Facilitator` mutations — pick a
   third-party package, scope the audit, and wire it into the existing
   panel views.

The two workstreams can ship in either order. History is more valuable
once CRUD is expanded (more mutations to record), so the plan sequences
CRUD first.

---

## Part A — Audit: what is actually editable today

Source: `ProposalEditPageView`, `ProposalCreatePageView`,
`ProposalRejectActionView`, `ProposalSetFacilitatorsActionView`
(`gates/web/django/chronology/panel/views/proposals.py`),
`FacilitatorEditPageView` (`.../views/facilitators.py`),
`SessionEditForm` (`gates/web/django/forms.py`), and
`Session` / `Facilitator` ORM models in `adapters/db/django/models.py`.

### Session fields

Target operation matrix from the product request, mapped to the
current panel state. `R` = read (rendered on detail page), `U` =
update (editable from edit form), `A`/`X` = add / remove (M2M
membership), `L` = link out (chip / row navigates to a related panel
page).

<!-- markdownlint-disable MD013 MD060 -->

| Field                  | Type                        | Target ops      | Today                              | Gap                                                                                                  |
| ---------------------- | --------------------------- | --------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `title`                | CharField                   | R U             | R U                                | —                                                                                                    |
| `slug`                 | SlugField                   | R               | —                                  | **Gap.** Derived from title; render read-only on detail page (debug aid for organizers).             |
| `display_name`         | CharField                   | R U             | R U                                | — **Canonical presenter byline.** Everything that shows "who is running this" on the event page and the panel sources from here, not from `Facilitator.display_name` (which is treated as a wizard auto-fill cache; see Facilitator matrix below). |
| `contact_email`        | EmailField                  | R U             | R U                                | —                                                                                                    |
| `description`          | TextField                   | R U             | R U                                | —                                                                                                    |
| `duration`             | CharField (ISO 8601)        | R U             | R U                                | — (validation is light; out of scope here)                                                           |
| `participants_limit`   | PositiveInt                 | R U             | R U                                | —                                                                                                    |
| `min_age`              | PositiveInt                 | R U             | R U                                | —                                                                                                    |
| `category`             | FK ProposalCategory         | R U             | Create-only                        | **Gap.** Step 2 adds reassignment.                                                                   |
| `status`               | CharField (`SessionStatus`) | R U             | Reject-only; enum missing values   | **Gap.** Step 1 adds enum values + accept / on-hold transitions.                                     |
| `facilitators`         | M2M Facilitator             | R A X L         | R A X (edit form + dedicated action) | **Gap-soft.** LINK to facilitator detail added in Step 8.                                          |
| `field_values`         | `SessionFieldValue` rows    | R U             | R U (dynamic block)                | —                                                                                                    |
| `time_slots`           | M2M TimeSlot                | R A X           | —                                  | **Gap.** Step 4.                                                                                     |
| `tracks`               | M2M Track                   | R A X L         | List-page filter only              | **Gap.** Step 3 adds assignment + LINK on each chip.                                                  |
| `presenter`            | FK User (nullable)          | R               | R                                  | — (already shown on detail page). Not editable in v1 — accepted.                                     |
| `creation_time`        | auto_now_add                | R               | —                                  | **Gap.** Render on detail page.                                                                      |
| `modification_time`    | auto_now                    | R               | —                                  | **Gap.** Render on detail page.                                                                      |
| `agenda_item`          | OneToOne reverse            | R L             | —                                  | **Gap.** When scheduled, render placement (space + start/end) and LINK to the timetable view with that track / date selected. |
| `schedule_change_logs` | reverse FK                  | R               | —                                  | **Gap.** Render a chronological list of placement changes on the detail page.                        |
| `ImportLogEntry`       | reverse-ish via importer    | R L             | R L                                | — (already rendered + linked at top of `proposal-detail.html`).                                      |
| `sphere`               | FK Sphere                   | (n/a)           | —                                  | Intentionally immutable; out of scope.                                                               |
| `participants`         | M2M through Participation   | (n/a)           | —                                  | Enrollment surface, not proposal CRUD. Out of scope.                                                 |
| `requirements`         | TextField                   | (legacy)        | R U (today)                        | **Legacy.** Stop rendering on detail page; remove from edit form. Step 5 cleanup.                    |
| `needs`                | TextField                   | (legacy)        | R U (today)                        | **Legacy.** Stop rendering on detail page; remove from edit form. Step 5 cleanup.                    |
| `tags`                 | M2M Tag                     | (legacy)        | —                                  | **Legacy.** Do not surface in the panel. No new UI; if a stub render exists, remove it.              |

<!-- markdownlint-enable MD013 MD060 -->

### Facilitator fields

`Facilitator.display_name` is **a wizard auto-fill cache**, not the
canonical presenter name. The canonical name lives on
`Session.display_name` (see Session matrix above). The panel may
surface the cached value for context, but it is **read-only** there —
no edit form, no relabel-via-bulk-edit. Editing the value would either
desync from the wizard pre-fill behavior or silently overwrite a user's
cached `User.name`, depending on which side wrote last; neither is
useful. Updates to the cache happen only through the natural wizard /
import flow.

Why surface it at all if it's a cache? Because it is also the only
human-readable identifier the panel has for a facilitator row — `slug`
is derived noise, `user` can be `NULL`. Hiding the cached name would
make the bottom "Facilitators" card and the facilitator list page
read as anonymous slug salad. The alternative — show but make
non-editable — keeps recognition without inviting bulk relabels.

<!-- markdownlint-disable MD013 MD060 -->

| Field                          | Type             | Target ops | Today                                | Gap                                                                                                  |
| ------------------------------ | ---------------- | ---------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| `user`                         | FK User (null)   | R          | Not surfaced                         | **Gap.** Render the linked user (display name + email, no link — no panel `user-detail` page exists). |
| `slug`                         | SlugField        | R          | Already used as URL key              | Render on detail page as a debug aid. **Gap-soft.**                                                  |
| `display_name`                 | CharField        | R          | Editable                             | **Gap.** Drop `display_name` from `FacilitatorEditPageView` form. Render read-only on detail page. Step 11 cleanup. |
| `sessions`                     | reverse M2M      | R L        | Not surfaced                         | **Gap.** Render the list of sessions this facilitator is attached to; each row LINKs to `panel:proposal-detail`. Step 11. |
| `HostPersonalData` (per-event) | per-event values | R U        | R U (via `FacilitatorEditPageView`)  | OK — stays editable. Step 6 also exposes inline edit on the proposal-edit page.                      |
| `event`                        | FK Event         | (n/a)      | —                                    | Immutable; correct.                                                                                  |

<!-- markdownlint-enable MD013 MD060 -->

### Status enum gap

`SessionStatus` in `pacts/legacy.py` only defines `PENDING`, `REJECTED`,
`SCHEDULED`. The product needs **`ACCEPTED`** (approved but not yet
scheduled) and **`ON_HOLD`** (reserve list). `SCHEDULED` stays as the
post-timetabling state and is set by the schedule editor, not the
proposal panel.

### Architectural note (CLAUDE.md compliance)

The current proposal views call `request.di.uow.sessions.update(...)`
directly. CLAUDE.md is explicit: **new code must use `request.services`,
not extend `request.di.uow`.** Every new mutation introduced by this plan
must go through a service in `mills/`. The strangler-fig migration of the
existing edit form is out of scope of this plan (separate task in
`docs/agents/services-migration.md`) — but new endpoints (accept /
on-hold / tags / tracks / time-slots / category-reassign / personal-data
inline) ship through a service from day one. This avoids regressing the
service-migration story.

---

## Part B — CRUD completion plan

The user-facing goal is a single proposal-edit page that exposes every
organizer-relevant field, plus three status-change action buttons on
both the list and detail pages.

Per CLAUDE.md ("Plan steps must be incremental and actionable — every
step reachable + demoable through the UI"), each step ends with the
operator being able to do something new from the panel.

### Step 1 — Status enum: `ACCEPTED` + `ON_HOLD`; accept/hold/reject actions

Demoable outcome: organizer can flip a proposal between Pending /
Accepted / On hold / Rejected from the proposal-detail page; rejection
button continues to work.

- `SessionStatus` (in `pacts/legacy.py`): add `ACCEPTED = auto()` and
  `ON_HOLD = auto()`. Translations for the new values land in
  `locale/pl/LC_MESSAGES/django.po`.
- Migration: the `status` field on `Session` is a `CharField` with
  `choices=[(item.value, item.name) for item in SessionStatus]`. Django
  picks the choices up at runtime; a Django `makemigrations` run will
  still emit a migration because the `choices=` kwarg is included in the
  field signature. Generate it and check it in.
- New service `ProposalStatusService` in `mills/submissions.py`:
  - `mark_accepted(*, event_id, proposal_id)`
  - `mark_on_hold(*, event_id, proposal_id)`
  - `mark_rejected(*, event_id, proposal_id)`
  - All three validate event scoping (proposal belongs to the given
    event), set the status, and return the updated `SessionDTO`.
  - Wire into `inits/services.py` and `Services` protocol in
    `pacts/`. Repo dependency: `SessionRepository` (already wired into
    `MillsRepos`).
- Action views (`gates/web/django/chronology/panel/views/proposals.py`):
  - New `ProposalAcceptActionView`, `ProposalHoldActionView`.
  - Refactor `ProposalRejectActionView` to call the new service (so all
    three transitions go through one code path).
  - URL names: `panel:proposal-accept`, `panel:proposal-hold`,
    `panel:proposal-reject` (existing).
- Templates:
  - `panel/proposal-detail.html`: replace the lone "Reject" button with a
    status-actions row showing all three buttons. Active status is
    highlighted (e.g. a colored badge near the title) and its button is
    disabled.
  - `panel/proposals.html` (list): status badge column already exists
    (or a Status column needs adding — confirm and add if missing). No
    inline buttons in the list view in v1; users click into detail to
    transition.
- Integration tests in `tests/integration/gates/web/django/chronology/panel/`:
  - One test per transition (pending → accepted, pending → on-hold,
    pending → rejected, accepted → on-hold, etc.).
  - Use `assert_response` + exact `context_data` matches.
- Per-step verification: `mise run check && mise run test`.

### Step 2 — Expose `category` reassignment

Demoable outcome: organizer can change a proposal's category from the
edit form.

- Extend `SessionEditForm` (and the dynamic factory `create_proposal_form`)
  by lifting the `category_id` `ChoiceField` from the create-only factory
  into the base form, defaulting to the current category. The factory
  collapses to a thin alias once the field is shared.
- New service method `ProposalEditService.reassign_category(*, event_id,
  proposal_id, category_id)` — or fold this into the broader
  `ProposalEditService` introduced in Step 5 below. For Step 2, ship the
  minimal method.
- Wire `ProposalEditPageView` to pass the chosen category through the
  service rather than through `request.di.uow.sessions.update(...)` for
  this field only. (The other fields stay on the legacy path for now —
  Step 5 migrates them en masse so the test churn is bounded.)
- Template: add a `<select>` for category just under the title field on
  `proposal-edit.html`. Show the category name on `proposal-detail.html`
  if not already shown.
- Tests: integration test that posting a new `category_id` updates the
  proposal; verify category-required session/personal-data fields
  re-resolve correctly (a category swap can change which fields are
  required). The existing CFP-side requirement logic should still apply.

### Step 3 — Tracks

Demoable outcome: organizer assigns one or more tracks to a proposal
from the edit form; track chips render on the detail page.

- `SessionRepository.set_session_tracks` already exists and is called
  from `mills/legacy.py` and `mills/submissions.py`. Surface it from a
  service method `ProposalEditService.set_tracks(*, event_id,
  proposal_id, track_ids)` with event-scope validation against
  `TrackRepository.list_by_event(event_pk)`.
- Track-manager permission check: the panel already differentiates
  "managed" tracks (`managed_track_pks`) on the list page. Organizer
  permission to assign any track on the event is assumed for now (no
  per-track restriction). Confirm with product before shipping; default
  is "any organizer can assign any track on the event".
- Template: multi-select (compact, since tracks are typically few) on
  `proposal-edit.html`. Detail page: track chips render in their own
  card; each chip is an `<a>` to the track's panel detail page
  (`panel:track-detail` or equivalent — confirm the actual URL name
  when implementing). Match the link styling used on the facilitator
  chips introduced in Step 8.
- Tests: include a case that submits a track from a different event and
  verifies it's ignored (matching the existing pattern from facilitator
  assignment). Assert on the rendered template that each track chip on
  the detail page renders as an anchor pointing at the track's panel
  page.

### Step 4 — Time-slot preferences

Demoable outcome: organizer can review and edit the facilitator's
preferred time slots from the edit form.

- Repo: `SessionRepository.read_time_slots(session_pk)` and
  `set_time_slots(session_pk, time_slot_pks)`. Check the model for
  existing methods first (`PendingSessionDTO` already carries
  `time_slots`, so a reader exists; the setter likely does not).
- Service: `ProposalEditService.set_time_slots(*, event_id, proposal_id,
  time_slot_ids)`; validates that every supplied slot belongs to the
  event.
- Template: multi-select grouped by day on `proposal-edit.html`. The
  organizer-facing copy makes clear these are *facilitator preferences*,
  not a scheduling decision.
- Tests: include event-scoping check; empty selection is allowed.

### Step 5 — Migrate `ProposalEditPageView` to a service + retire legacy fields

Demoable outcome: no visible change for the editable surface — but
`request.di.uow.sessions` disappears from the panel proposal views,
and the legacy `requirements`, `needs`, `tags` fields no longer
appear in the form or on the detail page.

- Consolidate `ProposalEditService` to expose a single
  `update_basic_fields(*, event_id, proposal_id, data: ProposalEditData)`
  method covering title, display_name, description, contact_email,
  participants_limit, min_age, duration (plus category from Step 2 if
  folded in). **Excludes** `requirements`, `needs`, `tags` — legacy.
- Replace the direct `request.di.uow.sessions.update(...)` call in
  `ProposalEditPageView.post`.
- Strip `requirements` and `needs` fields from `SessionEditForm` and
  the dynamic `create_proposal_form` factory in
  `gates/web/django/forms.py`. Remove their rendering blocks from
  `panel/proposal-edit.html` and the read-out blocks from
  `panel/proposal-detail.html`. No new migration — model columns are
  left in place, the data is simply no longer surfaced via the panel.
- Confirm `tags` is not exposed on either template (Step 3 added
  tracks, not tags); if a tag chip render is left over from older
  work, drop it.
- Move facilitator assignment in the same view to a service method
  (`ProposalEditService.set_facilitators`) and retire the duplicate code
  path in `ProposalSetFacilitatorsActionView` (it can call the same
  service).
- Tests: existing integration tests that asserted on requirements /
  needs / tags need updating — the assertions should disappear, not be
  rewritten to accept empty values. If a fixture path needs touching,
  prefer adjusting fixtures over the assertions.

### Step 6 — Personal-data inline on proposal edit

Demoable outcome: from a proposal-edit page the organizer can also see
and edit the personal-data fields of each assigned facilitator without
clicking through to the facilitator-edit page.

- Read-only first: render each assigned facilitator's `HostPersonalData`
  in a collapsible block on `proposal-edit.html`, sourcing from the
  same `personal_data_fields` + `host_personal_data` repos used in
  `FacilitatorEditPageView`.
- Then writable: a single POST handler accepts both
  `session_field_<slug>` and `facilitator_<fid>_personal_<slug>` keys.
  Personal-data writes go through a new service method
  `FacilitatorService.update_personal_data(*, event_id, facilitator_id,
  entries)` that wraps the same `HostPersonalDataRepository.save` call.
- Concurrency: a proposal may have multiple facilitators; the form
  groups personal-data inputs per facilitator. If a facilitator is
  shared between two proposals, last write wins — accept this for v1
  since the same is already true of the dedicated facilitator-edit page.
- Tests: integration test covering the combined save path.

### Step 7 — Detail-page polish + "no delete" policy enforcement

Demoable outcome: detail page reflects the new edit surface, drops the
duplicate "Facilitator" header at the top, and clearly shows no Delete
button anywhere.

- Detail page (`proposal-detail.html`):
  - Status row (from Step 1).
  - Track chips (Step 3) — each chip links to track detail page.
  - Time-slot preferences read-out (Step 4).
  - Category badge (Step 2).
  - Read-only metadata + scheduling/change-log surface (Step 9): slug,
    creation_time, modification_time, agenda-item placement + link,
    schedule-change-log list. ImportLogEntry link is already present.
  - "Edit" button as today.
- **Resolve the duplicate-name confusion.** Today the template renders
  two cards under similar headings: the top card is titled
  `{% translate "Facilitator" %}` but actually shows
  `proposal.display_name` (the canonical presenter byline) + linked
  presenter `User` + contact email; the bottom card is titled
  "Facilitators" and lists the assigned `Facilitator` rows with their
  own cached names. Rename the top card to a heading that names what
  it actually contains — e.g. "Presenter" — making it the single
  authoritative surface for "who is running this". The bottom card
  stays as the entity-list — same data, but its visible role is now
  navigation (LINK to facilitator-detail in Step 8) + read-only
  cached-name context, not naming-source-of-truth. Catalog the new
  heading string in `locale/pl/LC_MESSAGES/django.po`.
- Confirm there is no Delete button, link, or URL anywhere in the panel.
  Grep `panel:proposal-delete` to verify; if a stub exists, remove it.
- Documentation: a one-paragraph "Editing proposals" section in
  `docs/agents/architecture.md` or a sibling doc, linking the new
  service.

### Step 8 — Link facilitators on proposal detail to their facilitator page

Demoable outcome: from the proposal-detail page, the organizer clicks
into a facilitator row in the "Facilitators" card and lands on that
facilitator's detail page — where the linked `User`, personal-data
edit surface, and per-facilitator session list live.

The link is navigational, not naming-authoritative. The canonical
presenter name remains the one rendered in the top "Presenter" card
(sourced from `Session.display_name`, per Step 7). The bottom-card
labels are the cached `Facilitator.display_name`, useful as a
recognizable link target but not the source of truth.

- Template (`panel/proposal-detail.html`, "Facilitators" card around the
  `{% for f in facilitators %}` loop): wrap each `{{ f.display_name }}`
  in an `<a>` to the `panel:facilitator-detail` URL (args
  `slug=current_event.slug`, `facilitator_slug=f.slug`).
  Style with the existing link / hover utility classes (match the
  in-page link treatment already used for the import-log link earlier in
  the template) — don't roll a new style.
- DTO: `FacilitatorDTO` already carries `slug` (`pacts/legacy.py`); no
  service or repo change needed. Confirm `current_event` is in the view
  context (it is — set by the existing panel mixin).
- Scope: only the bottom "Facilitators" list card is in scope. The top
  card (retitled "Presenter" in Step 7) is a different surface —
  `Session.display_name` + linked presenter `User` + contact email — no
  panel `user-detail` page exists, leave it alone.
- Accessibility: link text is the cached `Facilitator.display_name`
  (not a generic "View"), so screen readers announce something useful.
- Tests: extend the existing proposal-detail integration test to assert
  the rendered HTML contains a link to
  `panel:facilitator-detail` for each assigned facilitator. Keep using
  `assert_response` with exact `context_data`; the link check is on the
  rendered template, not on context.
- Per-step verification: `mise run check && mise run test`.

### Step 9 — Detail-page read-only metadata, scheduling placement, and change log

Demoable outcome: from the proposal-detail page, the organizer sees
the slug, when the proposal was created and last modified, where it is
placed on the schedule (with a click-through to that timetable view),
and a chronological list of past placement changes.

Covers the remaining "R" / "R L" cells in the field matrix:
`slug`, `creation_time`, `modification_time`, `agenda_item`,
`schedule_change_logs`. `ImportLogEntry` is already rendered + linked
at the top of the template — confirm only.

- **Service** `ProposalDetailReadService` (extend the existing detail
  view's data path, or fold into `ProposalEditService` from Step 5
  under a new read method): one call returns a
  `ProposalDetailExtrasDTO` with the agenda-item placement (or
  `None`), the schedule-change-log list, and the metadata strings.
  Reuses `ScheduleChangeLogRepository.list_by_event` filtered to one
  session (add a `list_by_session(session_pk)` if needed) and a new
  `AgendaItemRepository.read_by_session(session_pk)` (already used by
  `TimetablePageView` — promote it from `request.di.uow` to a repo
  protocol if not already there).
- **DTOs** in `pacts/legacy.py`:
  - `AgendaItemDetailDTO` — `space_name`, `start_time`, `end_time`,
    `track_slug`, `date` (the day component of `start_time` in the
    event's timezone). Track is resolved via the space → area → venue
    chain; if the session has multiple tracks, pick the first
    intersecting one (or fall back to "any track" for the deep-link
    target). Confirm the actual deep-link target when implementing —
    `panel:timetable` accepts query params (see `_timetable_urlpatterns`
    in `panel/urls.py`).
  - `ProposalDetailExtrasDTO` — wraps `slug`, `creation_time`,
    `modification_time`, `Optional[AgendaItemDetailDTO]`, and
    `list[ScheduleChangeLogDTO]` (DTO already exists in
    `pacts/legacy.py`).
- **View** (`ProposalDetailPageView` in
  `panel/views/proposals.py`): add the extras to `context_data`. No
  new URL — the existing detail URL renders the new sections.
- **Template** (`proposal-detail.html`):
  - **Metadata strip** (below the title row): `Slug · Created · Last
    modified`. Use `|date:"DATETIME_FORMAT"` for the timestamps. Slug
    is plain text (selectable for copy-paste).
  - **Placement card** (only if `agenda_item is not None`): "Scheduled
    in {space} on {date} from {start} to {end}" with a "View on
    timetable" link to `panel:timetable` with the track/date
    preselected via query params (the timetable page already supports
    track + date selection — confirm the exact param names when
    implementing).
  - **Schedule-change-log card**: chronological list (oldest at
    bottom, matching the model's default ordering). Each row shows
    the action label, actor display name (or "system"), timestamp,
    and a compact "from X → to Y" if both old and new spaces /
    times are present.
- **Templates I18N**: section headers, "Scheduled in", "View on
  timetable", "Slug", "Created", "Last modified", "Change history"
  land in `locale/pl/LC_MESSAGES/django.po`. Polish: "punkt programu"
  conventions per CLAUDE.md.
- **Tests** in `tests/integration/web/panel/test_proposal_detail_page.py`:
  - Unscheduled proposal: extras DTO carries `agenda_item=None`;
    placement card is absent; metadata strip + (empty) change-log
    card are present.
  - Scheduled proposal: placement card renders with the correct
    `<a href>` to `panel:timetable` carrying the expected track/date
    query params; change-log card renders one assignment entry.
  - Reassigned proposal: change-log card renders both entries in
    order; from/to columns are correct.
  - Use `assert_response` with exact `context_data` matches on the
    new DTOs.
- Per-step verification: `mise run check && mise run test`.

### Step 10 — Proposals list view polish: pagination + facilitator column trim

Demoable outcome: the proposals list (`panel/proposals.html`) becomes
usable at scale — long display names no longer blow up row width, and
the list paginates instead of returning everything in one page.

- **Facilitator column trim** (`panel/proposals.html`, around the
  "Facilitator" column header / `{{ proposal.display_name }}` cell):
  - Today the cell is `whitespace-nowrap` and uncapped — long byline
    strings push the row wide.
  - Apply the same width-cap pattern the title column already uses:
    `max-w-xs truncate` plus `title="{{ proposal.display_name }}"`
    for the full string on hover. Match the existing Tailwind utility
    set; no new component.
  - Verify the header column "Facilitator" is misleading (the cell
    shows the session's `display_name`, not the M2M `Facilitator`).
    If a relabel is acceptable, rename to "Byline" or
    "Submitted as" — same string lands in
    `locale/pl/LC_MESSAGES/django.po`. Mark this sub-decision in
    Open question #7.
- **Category filter**:
  - A `<select>` above the table listing the event's `ProposalCategory`
    rows plus an "All categories" default; selecting one filters the list
    to proposals in that category. Sourced from
    `ProposalCategoryRepository.list_by_event(event_pk)`.
  - Threaded through `ProposalsListService.list_for_event` as a
    `category_id` filter and preserved across pagination / search links
    (same `request.GET.urlencode()` pattern as the other params).
  - Tests: seeding proposals across two categories, `?category=<id>`
    returns only that category's rows and round-trips through
    `context_data`; composes with `?page=` and `?search=`.
- **Pagination**:
  - `ProposalsListService.list_for_event(*, event_id, page, page_size,
    search, filters)` returns a `PaginatedProposalsDTO` with
    `items: list[ProposalListItemDTO]`, `page`, `total_pages`,
    `total_count`. Page size default: 50 (revisit after dogfooding).
  - Repo: `SessionRepository.list_sessions_by_event` gains paginated
    overload (or a new `list_sessions_by_event_paginated`) using
    Django's `Paginator`. Existing callers that need the unbounded
    list (e.g. exports) keep the old method.
  - View (`ProposalsListPageView` in `panel/views/proposals.py`):
    reads `?page=` from the query string, passes through service,
    puts the paginated DTO + page metadata into `context_data`.
    Preserves all existing filter / search query params across page
    links (use Django's `request.GET.urlencode()` pattern).
  - Template: a pagination strip below the table — previous / next +
    page indicator. Match existing pagination styling elsewhere in
    the panel; grep for "page_obj" / "paginator" in
    `templates/panel/` to find a reusable include. If none, add a
    minimal one rather than copying the markup inline.
- **Tests** in `tests/integration/web/panel/test_proposals_list_page.py`:
  - Seeding 60 proposals: page 1 shows 50, page 2 shows 10;
    `?page=2` round-trips through `context_data`.
  - Filters + search compose with pagination (e.g. `?page=2&search=foo`
    preserves the search across page links).
  - Edge cases: `?page=0`, `?page=999`, `?page=abc` → either clamp to
    page 1 or 404; pick one and assert on it.
  - Snapshot the rendered HTML around one row to assert the
    `max-w-xs truncate` + `title=` attribute on the byline cell.
- Per-step verification: `mise run check && mise run test`.

### Step 11 — Facilitator views: read-only name, sessions list, pagination

Demoable outcome: the facilitator list page paginates; the facilitator
detail page shows the linked user, slug, the cached display name
(read-only), and the list of attached sessions with a link to each
proposal-detail; the facilitator edit form no longer offers a
display-name input.

Closes the gaps in the Facilitator field matrix above:
`user` (R), `slug` (R), `display_name` (R-only), `sessions` (R L).
`HostPersonalData` editing on the dedicated facilitator-edit page stays
as today.

- **Drop `display_name` from the edit form.**
  `FacilitatorEditPageView` (`panel/views/facilitators.py`) and its
  form (`panel/views/facilitators.py` around the form construction +
  the matching template in `panel/facilitator-edit.html`) lose the
  `display_name` field entirely. The remaining form covers
  personal-data only. The view's POST handler stops calling
  `FacilitatorUpdateData(display_name=...)`; if that DTO has no other
  fields, retire it. The mills-side path that sets `display_name`
  during the wizard / import flows is untouched — the cache is
  populated there, never from the panel.
- **Facilitator detail surface** (`panel/facilitator-detail.html`,
  view: `FacilitatorDetailPageView` in `panel/views/facilitators.py`):
  - Render `display_name` as plain text (not an editable input) with
    a small "wizard auto-fill cache — see proposal display name for
    canonical value" hint underneath, i18n-catalogued.
  - Render the linked `User` (display name + email if present, or
    "—" if `user_id is None`). No link — there's no panel user-detail
    page (consistent with Step 8 scope).
  - Render the slug as a debug aid (small monospace text under the
    name).
  - **Sessions list**: a card listing every `Session` this
    facilitator is attached to. Each row shows the session title +
    status badge and is an `<a>` to `panel:proposal-detail`. Source
    via a new repo method `SessionRepository.list_by_facilitator(*,
    facilitator_id)` returning `list[SessionListItemDTO]` (reuse the
    existing list-item DTO from the proposals list to keep render
    parity); event scoping is implicit (a facilitator is per-event).
  - Service: extend the existing facilitator-detail data path (or
    introduce `FacilitatorDetailService.read(*, event_id,
    facilitator_id)` returning a `FacilitatorDetailDTO` that bundles
    the entity + sessions list).
- **Facilitator list page pagination**
  (`panel/facilitators.html`, view: `FacilitatorListPageView`):
  - Same shape as the proposals-list pagination from Step 10. New
    service method `FacilitatorListService.list_for_event(*,
    event_id, page, page_size, search)` returns a
    `PaginatedFacilitatorsDTO`. Page size default: 50.
  - Repo: `FacilitatorRepository` gains a paginated `list_by_event`
    overload (or a new paginated method).
  - View reads `?page=`, preserves search across page links.
  - Template: reuse the same pagination include introduced in Step 10
    — don't fork a second pagination component.
- **Tests** in
  `tests/integration/web/panel/test_facilitators.py` (or the existing
  facilitator-test module — confirm path):
  - Facilitator detail: assert sessions list renders the right
    proposals (event-scoped) and each row carries the expected
    `panel:proposal-detail` href; assert no `display_name` input is
    rendered on the edit page; assert the cached-name hint is
    rendered.
  - Facilitator list: seeding > page_size facilitators, `?page=2`
    round-trips through `context_data`; search query is preserved
    across page links.
- Per-step verification: `mise run check && mise run test`.

### Step 12 — Facilitator binding on hand-created proposals

Demoable outcome: when an organizer adds a new proposal by hand from the
panel, they bind it to an existing facilitator (picked from the event's
facilitators) or create a new facilitator inline, in the same form — no
separate trip to the facilitator list first.

Today `ProposalCreatePageView` creates the `Session` but leaves
facilitator attachment to the existing `ProposalSetFacilitatorsActionView`
flow after the fact. That forces a two-step dance and lets a freshly
hand-added proposal exist with zero facilitators.

- **Form** (`SessionEditForm` / `create_proposal_form` factory in
  `gates/web/django/forms.py`, create variant): add a facilitator
  block with two mutually-exclusive modes:
  - *Bind existing* — a `<select>` (or searchable list) of the event's
    `Facilitator` rows, sourced from
    `FacilitatorRepository.list_by_event(event_pk)`. Label shows the
    cached `display_name` + linked `User` email for disambiguation.
  - *Create new* — a small inline group (display name + optional
    contact email) that creates a `Facilitator` on submit. A
    user/account link is **not** required here — hand-added
    facilitators may have `user = NULL` (the model already allows it).
  - Mode switch is a radio/toggle; exactly one branch is validated on
    submit. At least one facilitator is required for a hand-created
    proposal (don't allow a zero-facilitator proposal through this
    path).
- **Service** — extend the proposal-create service path (the create
  counterpart to `ProposalEditService`) so a single
  `create_proposal(*, event_id, data, facilitator_ref)` call both
  inserts the `Session` and attaches the facilitator transactionally.
  `facilitator_ref` is a small DTO/union: either
  `{existing_facilitator_id}` or `{new: {display_name, contact_email}}`.
  The "create new" branch reuses the same facilitator-creation path the
  wizard/import flow uses (don't fork a second creation code path);
  event-scope the existing-id branch against
  `FacilitatorRepository.list_by_event`.
- **View** (`ProposalCreatePageView` in
  `panel/views/proposals.py`): pass the chosen facilitator reference
  through the service; on success redirect to the new proposal-detail
  page (the facilitator chip + "Presenter" card already render it via
  Steps 7–8).
- **Template** (`panel/proposal-create.html`): render the two-mode
  facilitator block under the core fields. Reuse the existing form /
  toggle styling from the tessera design system; don't hand-roll. New
  copy ("Bind existing facilitator", "Create new facilitator",
  field labels) lands in `locale/pl/LC_MESSAGES/django.po` — Polish
  "twórca programu" per CLAUDE.md.
- **Tests** in
  `tests/integration/web/panel/` (proposal-create module):
  - Create proposal binding an existing facilitator → proposal has
    that facilitator attached.
  - Create proposal with the "create new" branch → both the
    `Facilitator` and the `Session` exist and are linked, in one
    transaction.
  - Submitting an existing-facilitator id from a different event → it
    is rejected/ignored (matching the existing event-scoping pattern).
  - Submitting neither branch → validation error (no zero-facilitator
    proposal).
  - Use `assert_response` with exact `context_data` matches.
- Per-step verification: `mise run check && mise run test`.

---

## Part C — Edit-history audit trail

### Goal

Every mutation of `Session` and `Facilitator` (and arguably their value
side-tables `SessionFieldValue`, `HostPersonalData`) should leave a
durable trace that an organizer can browse. The trace must capture
*what* changed, *who* changed it, and *when*, and survive deletes of
related objects (e.g., a facilitator gone shouldn't erase the history of
proposals they were attached to).

### Option comparison

#### Option 1 — `django-simple-history`

Per-row, per-model history table. Every save creates a row in
`HistoricalSession` / `HistoricalFacilitator` with all field values plus
`history_user`, `history_date`, `history_type` (`+/-/~`), and
`history_change_reason`.

Pros:

- One table per tracked model; trivial mental model.
- Built-in `model_instance.history.as_of(datetime)` for point-in-time
  reads — useful for "what did this proposal look like when accepted?"
- Diffing between any two history rows is one method call.
- Admin integration; we don't use Django admin but custom panel views
  can read the history table directly.
- Pure-Django; no signals magic that breaks under bulk operations as
  long as we route mutations through the ORM (already the case via
  repos).
- Tracks M2M changes if you opt in per relation (`HistoricalRecords` +
  `m2m_fields`), so facilitators / tags / tracks / time_slots history
  is recoverable.

Cons:

- Table-size growth is linear with edits. Not a worry at our scale.
- "Who changed it" requires plumbing the request user into the
  ORM-save path. The library has a middleware that does this; with our
  service layer we'd inject the user via service methods instead.
- Bulk updates (`.update(...)`) bypass model `save()` and so bypass
  history. Our repos overwhelmingly use `.save()` and field-by-field
  M2M `.set(...)`, both of which trigger signals correctly. Worth an
  explicit audit pass.

#### Option 2 — `django-reversion`

Revision-based. A "revision" groups changes to multiple models; each
revision links to one or more "versions" (a JSON snapshot per object).
Designed around the admin's "save together" pattern.

Pros:

- Cross-model revisions (e.g., "user X accepted proposal Y" can group
  the Session row change + a comment + related-object changes into one
  revision).
- JSON-based snapshots — schema changes don't break old history.
- Revert-to-revision is a first-class operation.

Cons:

- Requires wrapping mutations in `with reversion.create_revision():`
  blocks. With a service layer that's mechanical but pervasive.
- JSON snapshots are awkward to query for "find all proposals where the
  category changed". Simple-history's flat schema is friendlier here.
- M2M tracking exists but is fiddlier than simple-history's
  `m2m_fields`.
- "Point-in-time read" is more verbose than simple-history's `as_of`.

#### Recommendation

**`django-simple-history`.** Reasons:

- Our audit need is dominated by per-row "what changed on this
  proposal" questions, which is exactly what simple-history is shaped
  for.
- The service-layer migration already gives us a clean place to attach
  the acting user without the library's middleware.
- M2M tracking for facilitators / tags / tracks / time_slots is a
  declared opt-in, fits our model.
- Revert-to-revision (reversion's strength) is not on the requirements
  list. The user asked for "changelog", not "rollback".

### Stepped rollout

Sequenced after Part B so the history captures the new mutation paths
from the start.

#### Step H1 — Install and configure (no UI yet)

- Add `django-simple-history` to `pyproject.toml`.
- Add `simple_history` to `INSTALLED_APPS` in `edges/settings.py`.
- Add `HistoricalRecords()` to `Session` and `Facilitator` with M2M opt-in
  for: `Session.facilitators`, `Session.tracks`, `Session.time_slots`.
  (`Session.tags` is legacy — not tracked; see Step 5.)
- Migration auto-generated.
- Acting-user wiring: extend each service method that mutates a
  `Session` or `Facilitator` to accept `actor_user_id: int` (or
  `actor: UserDTO`). The service sets `_history_user` on the model
  before save, using a thin helper in `links/db/django/repositories.py`
  that calls `model._history_user = actor` before `.save()`. Views pass
  `request.user.pk`.
- Verify: open a Django shell after running the new migration; mutate a
  session through the service; confirm a `HistoricalSession` row
  appears with the correct user, timestamp, and change type.
- No tests yet (no UI; smoke verification via shell).

#### Step H2 — Panel surface: history tab on proposal detail

Demoable outcome: organizer sees a chronological list of edits on a
proposal's detail page.

- New view `ProposalHistoryPageView` and template fragment (a tab on
  the existing detail page, not a separate URL).
- Service method `ProposalHistoryService.list_for_session(session_id)`
  returns a list of `ProposalHistoryEntryDTO` with: timestamp, actor
  display name (or `None` for system / import), change type, and a
  per-field "before → after" diff computed via simple-history's
  `diff_against`.
- Pagination not needed in v1 (we don't expect more than a few dozen
  edits per proposal). Add later if needed.
- Special-case the import path: when the importer creates or updates a
  proposal, the `_history_user` is `None` (system); the UI renders this
  as "Imported from {integration name}" using the existing
  `ImportLogEntry` link already present in `ProposalDetailPageView`.
- Tests: integration test that edits a proposal three times through
  three different users and verifies the history list contents.

#### Step H3 — Facilitator history surface

Same shape as H2 but on the facilitator detail page. Shares the DTO
pattern; the service method differs.

#### Step H4 — Personal-data + session-field-value history

The side-tables `SessionFieldValue` and `HostPersonalData` are the
high-churn surfaces; history-tracking them is what makes the trail
genuinely useful. Tracking them via simple-history is two more
`HistoricalRecords()` declarations + one more migration. UI: fold their
changes into the existing proposal-history / facilitator-history list
(not separate tabs).

---

## Open questions (to confirm before starting Step 1)

1. **Status mapping at scheduling time**: when a proposal currently in
   `ACCEPTED` gets placed on the timetable, does it auto-flip to
   `SCHEDULED`, or is `SCHEDULED` orthogonal to `ACCEPTED`? Current code
   treats `SCHEDULED` as a terminal status. Cleanest model is:
   `ACCEPTED` is a precondition for scheduling; placement transitions
   to `SCHEDULED`. Need to confirm what the existing schedule editor
   does with proposals whose status is not `SCHEDULED`.
2. **`ON_HOLD` semantics**: is it intended as "reserve list" (FIFO
   pool waiting for a scheduling slot) or just a parking lot? The label
   in the UI should match.
3. **Track-assignment permissions**: any organizer, or only the track's
   designated manager? The existing `managed_track_pks` plumbing hints
   the latter is meaningful elsewhere.
4. **Personal-data inline editing** (Step 6): is this actually wanted
   on the proposal edit page, or only on the facilitator edit page? The
   request reads "Session models fields, sessionfields and personalfields"
   — `personalfields` could mean "expose them on the proposal page" or
   "make sure the existing facilitator-edit page still covers them"
   (already does).
5. **History scope**: tracking M2Ms (facilitators, tracks, time_slots)
   doubles the history-row volume. Worth it? Recommendation is yes —
   those are the most operator-visible changes.
6. **Legacy field cleanup blast radius** (Step 5): removing
   `requirements`, `needs`, `tags` from the panel surface is confirmed.
   Open: leave the columns + data on the model (proposed) versus
   actually dropping them in a follow-up migration. Recommendation:
   leave alone; an unrelated reader / export might still consume them.
7. **List "Facilitator" column relabel** (Step 10): the column
   currently labeled "Facilitator" actually shows
   `session.display_name` (the submission byline). Acceptable to
   rename to "Byline" / "Submitted as", or keep the existing label and
   only trim the width?
8. **Cached-name hint copy** (Step 11): the facilitator-detail page
   will render a hint like "wizard auto-fill cache — see proposal
   display name for canonical value" near the read-only display name.
   Confirm wording / whether to surface this at all. Risk of being
   too internal-implementation-y; the alternative is to omit the hint
   and rely on the read-only styling alone.

---

## Out of scope

- Deleting proposals (explicitly disallowed by the request).
- Re-architecting `ProposalCategory` requirements when a category is
  reassigned mid-flight (Step 2 must handle it correctly, but the
  data-model itself stays).
- Schedule-editor changes (placement / unplacement remains its own
  surface).
- Migrating the entire panel away from `request.di.uow` — only the
  proposal-edit / proposal-status surfaces, as needed for the new
  features.
