# Plan — Lazy-load session detail modals

## Context / why

The event page (`chronology/event.html`) pre-renders **one full `<dialog>` modal
per session** (`{% for data in sessions %}`, ~lines 474–748): tabbed
info/participants, markdown description, session fields, participant + waiting
lists with avatars, edit-form target, and enroll actions. For a 110-session event
that is thousands of template-node renders on one response; a 600-session event
(see `tests/e2e/scripts/bootstrap_large_event.py`) scales linearly worse.

Symptoms traced to this:

- **django-debug-toolbar Templates panel** hangs/OOM-crashes runserver — faulthandler
  caught it in `debug_toolbar/panels/templates/panel.py:generate_stats`, which
  post-processes every rendered template.
- Baseline render cost grows with session count even with the toolbar off.

Already fixed separately (cheap, independent win): the `MARKDOWN` logger was
flooding the console at DEBUG on every `render_markdown` call — silenced in
`edges/settings.py`. WhiteNoise was a red herring (0.000 self-time; it only
looked hot because it is the outermost middleware and the toolbar sorts by
cumulative time).

## Goal

Render the event page with lightweight cards/rows only; fetch each session's
modal HTML on first open from a dedicated endpoint, inject it, then open it —
preserving the existing addressable-modal + view-transition "morph" system.

## Naming (per `docs/CODE_LAYOUT.md`)

A modal fragment loaded on demand is a **Component**, not a Page or Action:

- **view:** `SessionModalComponentView` — resource-first (matches `SessionEditView`,
  `SessionBookmarkToggleView`) + the mandated `ComponentView` suffix (matches
  `ProposeSessionCategoryComponentView` et al). NOT `SessionModalView`.
- **url name:** `session-modal` (matches `session-edit`, `session-propose-category`).
- **url path:** `event/<str:event_slug>/session/<int:session_id>/parts/modal`
  — noun, `parts/` prefix, no trailing slash (Component convention).
- **template:** `chronology/parts/session-modal.html` (alongside the existing
  `chronology/parts/session-enroll-actions.html`).

## Server changes — clean vertical slice (mills service + DTO)

Done the GLIMPSE way: data/business logic in a `mills` service returning `pacts`
DTOs; the view uses `request.services`; presentation assembly stays in `gates`.
**Model it exactly on the existing `party_session_history` slice** —
`PartySessionHistoryService` (mills) → `PartySessionHistoryDTO` (pacts) →
`present_party_history`/`_party_history_card` (gates) build `SessionData`. That
proves the whole pattern already works here.

1. **Extract the partial** (Step 1, done). `chronology/parts/session-modal.html`
   consumes a single `data: SessionData` plus `current_user`, `event`,
   `event_banned`, `request.session.anonymous_enrollment_active`.

2. **pacts** (`pacts/chronology.py`): add `SessionModalDTO` (mirror
   `PartySessionHistoryDTO`, plus the extra fields the modal needs:
   `field_values`, waiting-list seats, `viewer_waiting`, `can_edit`,
   `min_age`, `is_ongoing`/`is_ended`), a `SessionModalSeatDTO` (user + status +
   creation_time + `is_shadowbanned`), and `SessionModalServiceProtocol`. DTOs
   get `model_config = ConfigDict(from_attributes=True)`.

3. **links** (`links/db/django/repositories/sessions.py`): add a read returning
   the raw facts as DTOs (session + agenda + presenter + public field values +
   participations + counts + flags + location). ORM lives here, behind the repo
   protocol — models never leak past `links`.

4. **mills** (`mills/chronology` — new `SessionModalService` + protocol): given
   `event_id`, `session_id`, and the resolved **viewer** identity (+ companion
   ids), orchestrate the sessions/participations repos and return a
   `SessionModalDTO` (incl. `viewer_enrolled`/`viewer_waiting`). Django-free.
   404 signalled by returning `None`. The view resolves the viewer (authenticated
   vs anonymous-from-session, companions) and passes ids in — request-bound
   resolution stays in the view, not mills.

5. **inits** (`inits/services.py`, `inits/repositories.py`): wire the service as
   a flat `@cached_property` (`session_modal`) with its repo protocols +
   `TransactionProtocol`.

6. **gates**:
   - `present_session_modal(dto, *, event_banned, banned_presenter_ids) ->
     SessionData` in `event_presentation.py` — sibling of `_party_history_card`;
     builds `SessionData` and applies `mask_session_card`. Masking + shadowban
     ring stay presentation, fed by `request.services.{shadowban,event_bans}`
     results the view computes (same as the page and `present_party_history`).
   - `SessionModalComponentView` in `gates/web/django/chronology/views.py`
     (sibling of `SessionEditView`): GET by `event_slug` + `session_id`; 404 for
     unpublished-and-not-manager and for a `None` service result; calls
     `request.services.session_modal.read(...)`, then `present_session_modal(...)`,
     renders `chronology/parts/session-modal.html`. **`request.services.*`
     only — never `request.di.uow.*`.** Read-only, no transaction. Wire URL
     `event/<event_slug>/session/<session_id>/parts/modal` (name `session-modal`)
     in `chronology/urls.py`.

**Legacy `EventPageView` is left as-is** for now (strangler-fig): it keeps its
ORM path building `SessionData` inline. The modal is the clean beachhead; the
page migrates onto the same `session_modal` service later, at which point the
two paths converge. Tracked, not hidden — noted so the divergence window is
explicit.

1. **Remove** the modal `{% for %}` loop from `event.html` (Step 3). Cards/rows
   keep rendering from `sessions` / `schedule_days` (that `SessionData` is cheap;
   the modal *template* was the cost).

### Cache

`EventPageView` uses `cache_control(private=True, max_age=180)`. The modal shows
live enrollment/waiting data; start with **no** browser caching on the component
(or a short private max-age) and revisit if needed.

## Client changes (`src/ludamus/client/src/modal.ts`)

Triggers stay unchanged: `<a href="?session=<pk>" aria-controls="session-<pk>">`.

- Add `ensureModalLoaded(id)`: if `#session-<pk>` is absent, `fetch` the endpoint
  (URL derived from the container's `data-session-modal-url` attribute — a
  `reverse()`d URL with a `/session/0/` placeholder that is replaced with the
  requested session id), inject the returned `<dialog>` into that container, and
  resolve once present. Injected modals stay in the DOM (cache) so reopen +
  morph-close are instant.
- `await ensureModalLoaded(id)` before `openModal(id)` in all three entry points:
  the Navigation API `navigate` interception, the old-browser click fallback, and
  `syncModalsFromUrl` (deep-link `?session=<pk>` on load / popstate). The morph
  runs after injection, so the card→modal view-transition is unaffected.
- Loading affordance while fetching; on fetch failure, fall back to a full-page
  navigation (or inline error) so the feature degrades gracefully — mirrors
  `SessionEditView`'s non-HTMX fallback philosophy.

## Testing

- New **integration** test for `SessionModalComponentView` (gates layer): renders
  one session's modal; 404 when the event is unpublished and viewer is not a
  manager. Use `assert_response`; construct expected values exactly (no `ANY` for
  simple values).
- Update `EventPageView` tests that assert modal markup / per-session dialogs in
  the initial HTML — that markup moves to the component.
- e2e (`tests/e2e`): confirm opening a modal, deep-linking `?session=`, and the
  morph still work; a large-event smoke via the bootstrap script.

## Steps (each independently demoable)

1. Extract modal → `chronology/parts/session-modal.html`; page still includes it
   in the loop. *Demo:* event page byte-identical.
2. Add `build_session_data` + `SessionModalComponentView` + `session-modal` URL;
   endpoint renders the partial. *Demo:* GET the URL directly, see the modal HTML.
3. Switch `modal.ts` to lazy-load and delete the page's modal loop. *Demo:* open
   modals, deep-link, morph; large event renders fast, toolbar no longer chokes.
4. Tests (component + updated page tests) + e2e check.

## Out of scope

- Enroll / edit flows (already inside the modal partial; keep working unchanged).
- Schedule/card layout, filters, bookmarks.
- Debug-toolbar config (lazy-load removes the need; a one-line
  `DEBUG_TOOLBAR_CONFIG` guard can be added separately if still wanted).

## GLIMPSE review outcome

Reviewed against `docs/CODE_LAYOUT.md` + GLIMPSE. **Revised to the full clean
slice** (per direction: logic to `mills`, view uses `request.services`) rather
than a gates-only extraction:

- View naming `SessionModalComponentView` — Component grammar + session-scoped
  sibling style. New view in `gates`.
- Data/business logic → **`mills` service** returning `pacts` DTOs, wired in
  `inits`; ORM behind a `links` repo; presentation (`SessionData` + masking) in
  `gates`. Mirrors the existing `party_session_history` slice end to end.
- Data flow — views return DTOs; `request.services.*` only, no `request.di.uow.*`,
  no view-level transactions.
- Legacy `EventPageView` stays on its ORM path (strangler-fig); modal is the
  clean beachhead, page converges onto the same service later — the divergence
  window is explicit, not hidden.

## Consults during build

`product-design` (loading/error states, copy), `hector` (HTMX), `manuel`
(manual scenarios).
