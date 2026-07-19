# PLAN: Unify proposals & facilitators panels

Two panels, same job (filter → table → act → CRUD), built twice with different
answers. Goal: make them **work the same** — same filtering behavior, same
table affordances, same pagination, same code shape — by porting the best
pattern from each side and deleting the worse one. Not one merged panel; two
panels that feel like siblings.

## Current state (what differs)

<!-- markdownlint-disable MD013 -->
| Concern | Proposals (`views/proposals.py`) | Facilitators (`views/facilitators.py`) | Winner |
| --- | --- | --- | --- |
| Filtering | HTMX autosubmit (`hx-select`, `hx-push-url`, spinner, `filter-autosubmit.ts`) | Full-page GET submit with Filter button | Proposals |
| Search depth | title/basic fields only | display name only | Neither — search all text field values |
| Sorting | none | `_sort_th.html`, aria-sort, `{% querystring %}` | Facilitators |
| Columns | fixed | configurable via `EventPanelSettings` + columns chooser page | Facilitators |
| Pagination | hand-rolled prev/next in template | hand-rolled prev/next in template (a second copy) | Neither — one partial, size selector |
| Bulk actions | checkbox column + `bulk-status.ts` + safe-`next` | none (per-row inline forms only) | Proposals |
| Change history | event-wide `content-log` page, detail page shows schedule logs inline | event-wide `content-log` page only | Neither — per-item history tab on detail |
| List data access | legacy `request.di.uow.sessions.list_sessions_by_event` + in-view `Paginator` | `request.services.facilitator_panel.list_context(query)` (mills service, `FacilitatorListQuery`) | Facilitators |
| CRUD data access | mixed: status/delete/content-edit via services, create/reads via uow | mixed: list/flag via services, detail/create/edit reads via uow | Neither — finish the migration for these views |
| Action URLs | `/do/<action>` POST views, safe-`next` | same | Already unified |
| Empty states | filtered vs truly-empty, create CTA | same | Already unified |
| Status badges | `_proposal_status_badge.html`, but re-implemented inline in "Recently deleted" | n/a | Fix the duplication |
| Merge | n/a | filter-a-list-and-tick view; silent value loss on conflict | Redesign: search-and-collect, reconciled, explicit confirm |
<!-- markdownlint-enable MD013 -->

## Design decisions

1. **HTMX live filtering everywhere.** Facilitators list adopts the proposals
   pattern (`hx-get` on the filter form, `hx-select`/`hx-target` on a results
   container, `hx-push-url`, `data-autosubmit`, shared spinner). Filter button
   dies; Clear stays.
2. **Sortable headers everywhere.** `_sort_th.html` moves to
   `templates/panel/parts/` and proposals list gains sort on its natural
   columns. Sort key handling lives in the list query DTO, not the template.
3. **One pagination partial, user-set page size.** `templates/panel/parts/`
   `_pagination.html` (prev/next, "page X of Y", `{% querystring %}`) plus a
   page-size select — 10 / 20 / 50 / 100, **default 20** — carried as a query
   param, autosubmitted like any other filter. Used by both lists; the two
   inline copies and the hardcoded 50s die.
4. **Search looks inside field values.** List search matches text-type
   **session field values** on proposals and text-type **personal data field
   values** on facilitators, in addition to the built-in columns. Implemented
   at repo level (join + icontains), not by loading everything into Python.
5. **List views talk to mills services.** `FacilitatorPanelService.list_context`
   is the template: introduce `ProposalPanelService.list_context` taking a
   `ProposalListQuery` (search, category, status incl. the `scheduled`
   pseudo-status, track scope, field filters, sort, page, page size) and
   returning a ready-to-render context DTO. Filtering/sorting/pagination
   logic leaves the 1260-line view; unit tests move to mills level.
6. **CRUD views finish the services migration.** Facilitator detail/create/edit
   reads move off `request.di.uow` (extend `FacilitatorPanelService` /
   `PersonalDataFieldValueService`); proposal create write path moves off uow
   the same way `session_content_edit` already did for edit. No new
   `request.di.uow` surface anywhere in these two view files when done.
7. **Detail pages get tabs.** Proposal detail and facilitator detail both use
   `tab_shell` with a **Details** tab and a **Change history** tab scoped to
   that one item (proposals: content-edit log + schedule logs; facilitators:
   `FacilitatorChangeLog`). The event-wide `content-log` page stays as the
   cross-item view.
8. **Configurable columns on both lists.** Port the facilitators columns
   feature (chooser page, `EventPanelSettings` storage, reorder TS asset) to
   proposals, generalized rather than copy-pasted.
9. **Bulk actions on both lists.** Facilitators get the checkbox column +
   select-all pattern for bulk flag / unflag / mark-guest, plus a
   "Merge selected" entry into the merge flow.
10. **Merge becomes reconciled and search-driven — and stays irreversible.**
    - *Semantics:* as today, sessions are reassigned to the chosen target and
      sources are deleted — but the reconciled attribute choices are applied
      to the target first, so nothing is lost *silently*. Undo was considered
      and rejected: both variants (merge records + restore, or a faux
      facilitator linking to merged ones) buy little and cost a lot — the
      linking variant in particular turns every session/facilitator read into
      a query fan-out.
    - *Reconciliation:* where sources disagree (display name, accreditation,
      personal field values), the confirm screen asks — per-attribute choice,
      prefilled when all sources agree.
    - *Confirmation:* final submit goes through an explicit "This cannot be
      undone. Merge N facilitators?" dialog (same `data-confirm` pattern as
      delete actions).
    - *UX:* the merge tab stops being a filtered list. It becomes
      search-and-collect: search "Adam" → add Adam Kowalski to the selection
      basket, search "Jan Wysocki" → add him, then merge the basket. The
      basket lives in the form (hidden inputs), search results come in via
      HTMX — no server-side draft state.
11. **Keep full-page CRUD.** Both panels already do full-page create/edit/detail
    with `/do/` POST actions — that's the unified shape. No modals.
12. **Terminology pass.** Proposals surface mixes "Proposals" / "Create
    Session" / "Session deleted". Align user-facing copy to one noun per
    surface, following the Polish translation conventions in CLAUDE.md
    ("rodzaj atrakcji" participant-facing, "kategoria" in panel).

## Steps

Each step is independently shippable, demoable in the UI, and ends with
`mise run check && mise run test:py` green plus a screenshot of the affected
page (`mise run shots`). Steps touching user-facing copy update the i18n
catalog (makemessages via mise, fix empty **and** fuzzy entries).

### Phase 1 — list ergonomics

**Step 1 — Shared pagination partial + page size.**
Extract `templates/panel/parts/_pagination.html` with the 10/20/50/100
selector, default 20; page size flows through the list query. Use it in
`proposals.html` and `facilitators.html`; delete both inline copies and the
duplicated `_PAGE_SIZE = 50` constants (view + tests).
Demo: page through both lists, switch page size, filters survive.

**Step 2 — Sortable headers on proposals list.**
Move `_sort_th.html` under `templates/panel/parts/`; add sort params to the
proposals list (title, category, status, submission date; default unchanged).
Update `facilitators.html` include path.
Demo: click headers on `/event/<slug>/proposals/`, aria-sort + arrows behave
like the facilitators list.

**Step 3 — HTMX live filtering on facilitators list.**
Wrap the facilitators results (table + pagination + empty states) in a
`#facilitators-results` container; give the filter form the proposals-style
HTMX attributes + `data-autosubmit` (reuses `filter-autosubmit.ts` as-is).
Remove the Filter button, keep Clear. Plain-GET fallback keeps working.
Demo: change a filter on `/event/<slug>/facilitators/`, table updates without
a page load; URL updates; back button works.

**Step 4 — Deep search.**
Repo-level search across text field values: session fields for proposals,
personal data fields for facilitators (join + icontains, distinct). Guard
against matching other events' values.
Demo: search a phrase that only appears in a custom text field; the row shows
up in both lists.

**Step 5 — Copy & badge cleanup.**
"Recently deleted" table reuses `_proposal_status_badge.html`; terminology
pass over both panels (decision 12); align create/edit page chrome (header
actions: Cancel + submit via `form=` attribute).
Demo: walk both panels; nouns consistent, badges identical.

### Phase 2 — detail pages

**Step 6 — Detail tabs with per-item change history.**
Proposal detail and facilitator detail get `tab_shell` tabs: Details |
Change history. History tab reuses the `content-log.html` rendering (extract
a shared log-list partial), filtered to the one session / facilitator.
Revert stays on the event-wide log page for now.
Demo: open both detail pages, switch tabs, see only that item's history.

### Phase 3 — code shape

**Step 7 — `ProposalPanelService.list_context`.**
New mills service mirroring `FacilitatorPanelService`: `ProposalListQuery` +
context DTO in `pacts/`, repos dataclass, wired in `inits/services.py`.
`ProposalsPageView.get` shrinks to: parse query params → call service →
render. In-view `Paginator` and the dict-shaped filter arg to
`sessions.list_sessions_by_event` go away. Field-filter tamper-guarding
copies the `_resolve_field_filters` approach.
Verification: existing `test_proposals_page.py` passes (same context
contract); new unit tests for the mill; `tingle stat --diff` shows uow
surface shrinking, not growing.

**Step 8 — Facilitator CRUD off `request.di.uow`.**
Migrate `FacilitatorDetailPageView`, `FacilitatorCreatePageView`,
`FacilitatorEditPageView` reads to services (extend `FacilitatorPanelService`
with `detail_context` / create support, per
`docs/agents/services-migration.md`).
Verification: no `request.di.uow` left in `views/facilitators.py` outside
merge (replaced in step 12); existing integration tests pass.

**Step 9 — Proposal create off `request.di.uow`.**
Move `ProposalCreatePageView.post` writes (slug, create, field values, time
slots) into a service method alongside `session_content_edit`, same
transactional shape as facilitator create.
Verification: no uow writes left in the create path;
`test_proposal_create_page.py` passes.

### Phase 4 — feature ports

**Step 10 — Configurable columns for proposals.**
Generalize the columns chooser (page view, `EventPanelSettings` storage key
per list, `facilitator-columns.ts` → shared `panel-columns.ts`) and add a
Columns tab + column-driven rendering to the proposals list, reusing the
one-string-per-cell projection approach from `_build_column_values`.
Demo: `/event/<slug>/proposals/columns/` works like the facilitators one.

**Step 11 — Bulk actions for facilitators.**
Checkbox column + select-all reusing the `bulk-status.ts` pattern; bulk
flag / unflag / mark-guest via `/do/bulk-...` POST views with safe-`next`
and per-outcome counts, like `ProposalBulkStatusActionView`. A
"Merge selected" button pre-fills the merge basket (lands fully in step 14).
Demo: select rows on the facilitators list, bulk-flag them.

### Phase 5 — merge redesign

**Step 12 — Merge reconciliation service.**
Extend the merge service in mills (moved behind `request.services`, no more
hand-instantiation): merge takes the target, source ids, and reconciled
attribute choices (display name, accreditation, personal field values);
applies choices to the target and reassigns sessions and deletes sources in
one transaction. The >1-linked-user guard stays; the duplicated selection
validation in the view goes (service already checks).
Verification: unit tests for reconciled-value application, conflict
detection, and the linked-user guard.

**Step 13 — Merge UI: search-and-collect + reconcile + confirm.**
Merge tab becomes: search box (HTMX results with "Add" buttons) + selection
basket (hidden inputs, removable chips/rows) + "Merge N selected" → confirm
screen with target choice and per-attribute reconciliation (prefilled when
sources agree) → final submit behind an explicit "This cannot be undone."
`data-confirm` dialog. "Merge selected" bulk action from step 11 jumps
straight to the pre-filled basket.
Demo: the Adam Kowalski / Jan Wysocki scenario — two searches, one basket,
a reconcile screen, one confirmed merge.

## Out of scope

- CFP category CRUD (`cfp.py`, `cfp-edit.html`) — separate sub-feature with
  its own debt (45KB template, duplicated POST context building); deserves
  its own plan.
- Participant-facing proposal wizard.
- Facilitator soft delete / merge undo — rejected: merge-record restore or a
  faux facilitator linking to merged ones both add query fan-out for a rarely
  needed escape hatch; reconciliation + explicit confirm covers the risk.
- The deferred `EventContext` typed-subdict refactor (tracked separately) —
  steps here must not flat-spread new context keys that make that flip harder.
- Merging the two panels into one screen — explicitly not the goal.
