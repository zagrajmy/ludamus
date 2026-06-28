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

- **Shipped:** the existing `create_proposal_form(choices)` factory already
  produces a `SessionEditForm` subclass with a required `category_id`
  `ChoiceField`. Rather than lift the field onto the base form (which would
  force a required category onto the facilitator self-edit path that also
  uses `SessionEditForm`, and fight django-stubs typing), the edit view now
  **reuses the same factory** for its GET/POST. Self-edit keeps the plain
  `SessionEditForm` and is untouched. The `ChoiceField` is scoped to the
  event's categories, so a foreign-event category fails `invalid_choice`
  validation for free (event-scoping without an extra check).
- **No new service method.** `ProposalEditPageView` already routes through
  `request.services.session_content_edit.apply(...)` (Step 5 was partly
  done). Category reassignment rides that existing service: `category_id`
  is added to the `SessionUpdateData`, which the repo's generic `update`
  already persists. `diff_session_content` records a `category` change in
  the content-change-log.
- Template: category `<select>` rendered just under the title field on
  `proposal-edit.html`; category name shown in the Details card on
  `proposal-detail.html` (`category_name` context key).
- Tests: integration test that posting a new `category_id` updates the
  proposal; verify category-required session/personal-data fields
  re-resolve correctly (a category swap can change which fields are
  required). The existing CFP-side requirement logic should still apply.

### Step 3 — Tracks

Demoable outcome: organizer assigns one or more tracks to a proposal
from the edit form; track chips render on the detail page.

- **Shipped:** `track_ids` rides the existing
  `SessionContentEditData` / `session_content_edit.apply` service (same
  pattern as `facilitator_ids`) — no new service method. The repo's
  `set_session_tracks` / `read_track_ids` were already in the protocol.
- **Event-scope validation** lives in the view's `_collect_track_ids`,
  which intersects submitted ids with `tracks.list_by_event(event_pk)`
  before passing them to the service (mirrors `_collect_facilitator_ids`).
- **Permissions:** per resolved Q3, **any organizer can assign any track**
  on the event — no per-track restriction.
- Template: compact checkbox list (tracks are few) with a
  `tracks_submitted` hidden marker on `proposal-edit.html`. Detail page:
  track chips in their own card; each chip is an `<a>` to
  **`panel:track-edit`** (`slug`, `track_slug`) — there is no
  `track-detail` page, and the edit page is the de-facto track page.
  Styled as bordered pills (`border-border` → `hover:border-primary`).
- Tests: assignment persists; a track from a different event is filtered
  out; a partial POST without the `tracks_submitted` marker preserves
  existing tracks; the detail page renders each chip as an anchor to
  `panel:track-edit`.

### Step 4 — Time-slot preferences

Demoable outcome: organizer can review and edit the facilitator's
preferred time slots from the edit form.

- **Shipped:** `time_slot_ids` rides the existing
  `SessionContentEditData` / `session_content_edit.apply` (same pattern as
  `facilitator_ids` / `track_ids`). Repo `set_time_slots` (writes the
  `time_slots` M2M) and `read_preferred_time_slot_ids` were already in the
  protocol — no new repo or service method.
- **Event-scope validation** in the view's `_collect_time_slot_ids`
  (intersect with `time_slots.list_by_event(event_pk)`).
- Template: checkbox list with a `time_slots_submitted` marker on
  `proposal-edit.html`; copy makes clear these are *facilitator
  preferences*, not a scheduling decision. Detail page already renders
  the preferred slots, unchanged.
  <!-- ponytail: flat list, not grouped-by-day — matches the existing
  detail-page rendering and avoids event-timezone bucketing. Group by day
  if slot counts grow large enough to need it. -->
- Tests: assignment persists; foreign-event slot is filtered out; the
  `time_slots_submitted` marker with no selection clears the slots (empty
  selection allowed); a partial POST without the marker preserves them.

### Step 5 — Migrate `ProposalEditPageView` to a service + retire legacy fields

Demoable outcome: the legacy `requirements`, `needs`, `tags` fields no
longer appear in the panel create / edit forms or on the detail page;
the editable surface is otherwise unchanged.

- **Update path already migrated.** Steps 2–4 routed
  `ProposalEditPageView.post` through `request.services.session_content_edit`
  (no `request.di.uow.sessions.update(...)` left in the edit view), so the
  "consolidate into a service" goal landed earlier. No new service method.
- **`requirements` / `needs` retired from the panel only (surgical, per
  the scope decision).** Removed from the panel create + edit templates,
  from `ProposalEditPageView` GET initial / POST update, and the read-out
  blocks on `proposal-detail.html`. The create view hardcodes them to `""`.
  `SessionEditForm` **keeps** both fields because it is shared with the
  facilitator self-edit (`web:chronology:session-edit`), which still
  surfaces them — stripping the shared form would have removed them there
  too. Model columns + data stay (Q6).
- `tags` is **already not exposed** in the panel (the `{% load cfp_tags %}`
  in `proposal-detail.html` is a template-tag library, not the `Tag`
  model). No-op — confirmed.
- Tests: regression tests assert the panel edit form and detail page no
  longer render `requirements` / `needs`; the obsolete keys were dropped
  from the create / edit POST fixtures.

**Deferred out of Step 5** (kept minimal per the surgical scope):

- `ProposalSetFacilitatorsActionView` still writes via
  `request.di.uow.sessions.set_facilitators`. It is registered
  (`panel:proposal-set-facilitators`) but **not referenced by any
  template** — the inline facilitators block on the edit form replaced it.
  Fold it into the service (or delete the dead endpoint) alongside the
  create-path migration.
- `ProposalCreatePageView` still calls `request.di.uow.sessions.create`.
  Migrate it in **Step 12**, which overhauls the create path for
  facilitator binding.

### Step 6 — Personal-data inline on proposal edit

Demoable outcome: from a proposal-edit page the organizer can also see
and edit the personal-data fields of each assigned facilitator without
clicking through to the facilitator-edit page.

- **Shipped (read + write in one pass).** Each assigned facilitator gets
  a collapsible `<details>` block (native HTML) on `proposal-edit.html`,
  sourced from the same `personal_data_fields` + `host_personal_data`
  repos as `FacilitatorEditPageView`.
- **Shared partial:** the personal-field input markup was extracted into
  `panel/_personal_data_fields.html`, parameterized by a `name_prefix`,
  and `facilitator-edit.html` was refactored to include it (prefix
  `personal`). The proposal-edit blocks use prefix
  `facilitator_<fid>_personal` so each facilitator's inputs are namespaced
  (id + name carry the prefix → no cross-facilitator collisions).
- **New service** `HostPersonalDataService.update_personal_data(*,
  event_id, facilitator_id, entries)` in
  `mills/submissions/personal_data_fields.py`, wired onto
  `request.services.host_personal_data`. It owns the transaction and
  event-scoping (`facilitators.read(id).event_id == event_id` else
  `NotFoundError`), then calls `HostPersonalDataRepository.save`. The
  proposal-edit POST calls it per facilitator.
- **Markers:** a `personal_data_submitted` hidden field guards the write
  (partial POSTs leave personal data untouched); a
  `personal_data_facilitator_ids` hidden field per block tells the POST
  which facilitators' inputs to parse. The view's `_collect_personal_data`
  intersects those ids with the event's facilitators for scoping.
- Concurrency: last-write-wins per facilitator (same as the dedicated
  facilitator-edit page) — accepted for v1.
- Tests: integration (render, save, foreign-event facilitator ignored)
  plus a unit test for the service's event-scoping + save path.

### Step 7 — Detail-page polish (presenter-card rename)

Demoable outcome: the proposal-detail page no longer has the misleading
duplicate "Facilitator" heading at the top — it reads "Presenter",
naming what the card actually shows.

The rest of the detail-page surface this step originally bundled already
landed in earlier steps: status row (Step 1), track chips (Step 3),
time-slot read-out (Step 4), category badge (Step 2). The read-only
metadata + scheduling/change-log surface is **Step 9**.

- **Shipped:** renamed the top card heading from `Facilitator` to
  **`Presenter`** in `proposal-detail.html`. The card already shows
  `proposal.display_name` (the canonical byline) + linked presenter
  `User` + contact email, so it is now the single authoritative
  "who is running this" surface. The bottom "Facilitators" entity-list
  stays (Step 8 adds links to it). New `Presenter` string catalogued in
  `locale/pl/LC_MESSAGES/django.po`.

- **"No-delete policy" dropped — decision: keep the soft-delete.** The
  panel already has a complete, tested **soft-delete + restore** flow
  (`ProposalDeleteActionView` / `ProposalRestoreActionView`,
  `session_deletion` service, the deleted-proposals restore section on
  the list page). Because it is reversible — not the destructive delete
  the original request disallowed — it stays as-is. The Delete button on
  the detail page remains. The "Out of scope: deleting proposals" line
  below refers to *hard* deletion, which still does not exist.

- Documentation deferred: the plan itself documents the edit surface;
  a dedicated `docs/agents` write-up can follow if needed (the new
  services are `session_content_edit` and `host_personal_data`).

### Step 8 — Link facilitators on proposal detail to their facilitator page

**Shipped.** Each row in the bottom "Facilitators" card on
`proposal-detail.html` is now an `<a>` to `panel:facilitator-detail`
(`slug=current_event.slug`, `facilitator_slug=f.slug`), styled with the
existing `text-primary hover:underline` treatment. `FacilitatorDTO`
already carried `slug`, so no service/repo change. A detail integration
test asserts the rendered `href`.

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

**Shipped.** Done with plain view reads + repo methods — no new DTOs or
read service (the heavier `ProposalDetailExtrasDTO` / `AgendaItemDetailDTO`
the plan sketched were unnecessary). Also delivers Part C's schedule-log
surface (C3's schedule half).

- **Metadata strip** below the breadcrumb: `Slug · Created · Last
  modified`, from `SessionDTO` (already carried all three), timestamps via
  `|date:"DATETIME_FORMAT"`, slug monospaced + `select-all`.
- **Placement card** (only when scheduled): the view reads
  `agenda_items.read_by_session(proposal_id)` → `AgendaItemDTO | None`.
  Per resolved Q1, "scheduled" is inferred from the agenda item existing,
  not a status. Card shows "Scheduled in {space}, {start} – {end}" with a
  "View on timetable" link to `panel:timetable?date=YYYY-MM-DD` (the
  timetable accepts a `date` param).
- **Schedule-change-log card**: new repo method
  `ScheduleChangeLogRepository.list_by_session(session_id)` (+ protocol);
  the view passes the list, the template reuses the existing
  Assigned/Removed/Reverted labels + `old → new` space rendering from
  `timetable-log.html`. Newest first (model default ordering).
- `ImportLogEntry` link was already present — confirmed.
- Tests: unscheduled (metadata present, no placement/schedule cards),
  scheduled (placement card + `?date=` timetable href), schedule-log
  renders an entry. Exact-context detail tests gained `agenda_item: None`
  - `schedule_logs: []`.

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

**Shipped** in two commits — 10a (column trim + relabel) and 10b
(category filter + pagination).

- **10a:** the "Facilitator" column (which shows the session byline) was
  relabelled **"Display Name"** (per resolved Q7) on both the active and
  deleted tables, and the cell capped with `max-w-xs truncate` +
  `title="…"`.
- **10b — category filter:** a "Category" `<select>` ("All categories"
  default) above the table; `?category=<id>` threads through the view to a
  new `category_pk` arg on `list_sessions_by_event`, validated against the
  event's categories (foreign ids ignored). Preserved across page links by
  the built-in `{% querystring %}` tag (Django 6).
- **10b — pagination:** the view paginates the already-loaded list with
  Django's `Paginator` (page size 50). `page_obj` goes in context
  (`ANY` in tests); a Prev/Next strip uses `{% querystring %}` so all
  filters survive page navigation. `get_page` clamps bad pages (non-int →
  1, out-of-range → last). Repo-level slicing deferred (ponytail comment).
- Tests: category filter (incl. foreign-event ignored), 60-row pagination
  (page sizes + clamping), byline trim/relabel render; the 11 exact-context
  list tests gained `page_obj`/`categories`/`filter_category_pk`.

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

**Shipped.**

- **Edit form drops `display_name`:** new `FacilitatorEditForm`
  (accreditation_type only); the create path keeps `FacilitatorForm`
  (display_name required at creation). The edit POST no longer passes
  `display_name` to `FacilitatorUpdateData`, so a posted value is ignored
  (test asserts the cache is unchanged). The edit template renders the
  cached name read-only with a hint pointing at the proposal's display
  name.
- **Detail surface:** read-only cached `display_name` + hint; linked
  `User` rendered as name · email (`active_users.read_by_id`, "—" when
  `user_id is None`); slug as a monospace debug aid; a **Sessions** card
  listing every attached session via new
  `SessionRepository.list_by_facilitator` (+ protocol) returning
  `SessionListItemDTO`, each row linking to `panel:proposal-detail` with a
  status badge.
- **List pagination:** `FacilitatorsPageView` paginates with Django's
  `Paginator` (page size 50), same Prev/Next `{% querystring %}` strip as
  the proposals list.
- Tests: edit (no display_name input, cache unchanged), detail (sessions
  link, linked-user name+email; exact-context blocks gained
  `linked_user`/`sessions`), list pagination; `Sessions` /
  `No sessions attached.` translated.

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

**Shipped** (per resolved Q4: **existing facilitator only**, no inline
create; the facilitator select comes **first** in the form).

- `create_proposal_form` gained an optional `facilitators` param — when
  passed (create variant only), it adds a **required**
  `facilitator_ids` `MultipleChoiceField`. The choices are the event's
  facilitators, so each id is validated against them: "at least one" comes
  free from `required`, and a foreign-event id fails `invalid_choice`
  (event-scoping without a manual check). The shared edit reuse of the
  factory passes no facilitators, so the edit form is unchanged.
- `ProposalCreatePageView` passes the validated `facilitator_ids` to the
  existing `sessions.create(..., facilitator_ids=...)` (the repo already
  accepts them and returns the new pk) and redirects to
  `panel:proposal-detail`. **No new service** — ponytail: the repo call
  already attaches in one step, and the importer uses the same path; a
  create-service wrapper for one existing call is scaffolding.
- Template: the facilitator checkbox list is the **first** field; when the
  event has no facilitators it shows a notice + link to
  `panel:facilitator-create` instead of an unsatisfiable required field.
- Tests: bind existing → attached + redirect to detail; no facilitator →
  validation error, no session; foreign-event id → rejected.

> Note: the Step-5-deferred migration of the create path off
> `request.di.uow.sessions.create` is **not** done here — it would mean
> wrapping a single existing repo call in a new service purely for
> architectural tidiness. Left for the broader services-migration task,
> same as the dead `ProposalSetFacilitatorsActionView` endpoint.

Demoable outcome: when an organizer adds a new proposal by hand from the
panel, they bind it to an existing facilitator (picked from the event's
facilitators), in the same form — no separate trip to the facilitator list
first.

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

## Part C — Complete the existing change-log (no new dependency)

**Decision (2026-06-28):** drop `django-simple-history` /
`django-reversion`. The codebase already ships a working, tested audit
trail — `ContentChangeLog` (session content edits) and
`ScheduleChangeLog` (timetable placement), browsable on the
`panel:content-log` page, plus `ImportLogEntry` for provenance. That
already satisfies the request ("changelog", not "rollback") for session
content + scheduling. Adding a parallel per-row history system would mean
a new dependency, per-model history tables, a migration, acting-user
plumbing, and *two* audit surfaces to reconcile. Instead we close the
genuine gaps by extending the log we already have.

### What the existing `ContentChangeLog` captures today

Written by `SessionContentEditService.apply` via `diff_session_content`:
core session columns (title, display_name, description, contact_email,
duration, participants_limit, min_age, cover_image, **category**) and
dynamic **session-field values** — each as `{field, field_id, old, new}`,
with acting user + timestamp. Rendered on `panel/content-log.html`
(`change.field|content_field_label` for core fields, `field_names`
lookup for dynamic ones).

### Gaps to close

1. **M2M assignment** — facilitators / tracks / time-slots. `apply()`
   writes them but `diff_session_content` does not diff them, so changes
   go unlogged. (Q5 confirmed these M2Ms are worth tracking.)
2. **`HostPersonalData`** — personal-data answers, including the Step 6
   inline write, log nothing.
3. **`Facilitator` entity edits** — display_name, accreditation_type.

### Step C1 — Log M2M assignment changes in `ContentChangeLog` ✅

**Shipped.** Changing a proposal's facilitators / tracks / time-slots from
the edit form now adds an `old → new` row to the content log.

- `SessionContentEditService.apply` reads each M2M's **old** membership
  before `set_*` and the **new** membership after, then `_append_m2m_change`
  appends `{field, field_id: None, old, new}` when they differ. Names are
  comma-joined and **sorted**, so a pure reorder isn't logged. Identity-only,
  like the core-field diff.
- Names come from `read_facilitators` (display_name), a new
  `SessionRepository.read_tracks` (+ protocol), and
  `read_preferred_time_slots` (ISO start - end labels).
- `content_field_label` (`cfp_tags.py`) gained `facilitators` / `tracks` /
  `time_slots` labels — plus `category` (which Step 2 logged but never
  labelled). No content-log template change — it already iterates `changes`.
- Tests: integration (facilitator change logged; re-submitting the same set
  logs nothing). The pure helper is exercised through the integration path
  (importing the private `_append_m2m_change` directly trips the
  no-private-import lint rule, and `noqa` is disallowed).

### Step C2 — Log personal-data edits

Demoable outcome: editing a facilitator's personal-data answers leaves a
trace.

- **Model fit caveat:** `ContentChangeLog` is session-scoped (`session`
  FK required); `HostPersonalData` is facilitator+event-scoped. Two
  viable shapes — pick when implementing:
  - (a) When edited via the **proposal-edit inline path** (a session is
    in context), attach the diff to that session's `ContentChangeLog`,
    labelled per facilitator. Leaves the dedicated facilitator-edit page
    path unlogged.
  - (b) Make `ContentChangeLog.session` nullable and add a nullable
    `facilitator` FK, so both edit paths log uniformly. One migration;
    the content-log page groups by session-or-facilitator.
- Recommendation: (b) if facilitator-edit auditing matters; (a) if only
  the proposal-edit surface needs it. Confirm before building.
- Tests: an inline personal-data edit writes a log entry; event-scoping
  preserved.

### Step C3 (optional) — Per-proposal history view on the detail page

Demoable outcome: the proposal-detail page shows this proposal's edits
without leaving for the event-wide log.

- Filter `ContentChangeLog` + `ScheduleChangeLog` to one session
  (`list_by_session`) and render a compact history card on
  `proposal-detail.html`. This also delivers the Step 9 "schedule-change-
  log list" surface from the same data. The import provenance is already
  linked at the top of the page.
- No new dependency, no new model — a read + a template card.

---

## Resolved decisions (answered 2026-06-28)

1. **Status mapping at scheduling time**: `SCHEDULED` is **orthogonal** and
   not needed as a status. "Scheduled" is inferred from the existence of an
   `agenda_item` (`agenda_item_id is not None`), not from a status value.
   `PENDING` / `ACCEPTED` / `ON_HOLD` / `REJECTED` are the real states;
   placement is a separate axis. Follow-up for later steps: stop treating
   `SCHEDULED` as a status and infer placement from the agenda item.
2. **`ON_HOLD` semantics**: **reserve list**.
3. **Track-assignment permissions**: **any organizer** can assign any track
   on the event. Organizers are assigned to tracks only for convenience,
   not as an access restriction.
4. **Hand-created proposal facilitator binding** (Step 12): allow **only
   selecting an existing facilitator** (no inline create). The facilitator
   select must come **first** in the form so the organizer doesn't have to
   abandon a filled-in form to go create a missing facilitator first.
5. **History scope**: **yes** — track the M2Ms (facilitators, tracks,
   time_slots).
6. **Legacy field cleanup blast radius** (Step 5): **leave the columns +
   data on the model**; only drop them from the panel surface.
7. **List "Facilitator" column relabel** (Step 10): **yes, relabel** — use
   "Display name" (the session byline) instead of the misleading
   "Facilitator".
8. **Facilitator display name** (Step 11): the canonical display name lives
   on the **session**, because a facilitator can participate in sessions
   facilitated by groups. Surface the session's display name as the
   canonical byline; the facilitator row's cached name is read-only context
   only.

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
