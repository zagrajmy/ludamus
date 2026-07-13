# 1. GLIMPSE strangler: `adapters/` → layered tree

**Status:** 🟡 in progress
**Tracked in TODO:** GLIMPSE epic (umbrella for items 1–4)

## Goal

Empty the legacy `adapters/` package. Every view, model, form and helper that
still lives under `ludamus.adapters.*` should move into its GLIMPSE home
(`gates`, `links`, `mills`, `pacts`), leaving `adapters/` to be deleted.

## Why

`adapters/` predates the layer rules and is **not governed by importlinter** —
the contracts in `pyproject.toml` cover `gates/links/mills/pacts/specs/inits`
but say nothing about `adapters`. Code there can import anything, so it is the
last place where layering can rot silently.

## Current state

The active `ROOT_URLCONF` is `ludamus.gates.web.django.urls`, but it still
`include()`s `ludamus.adapters.web.django.urls`, which routes the unmigrated
views. What remains in `adapters/`:

- **`adapters/web/django/views.py`** still hosts:
  - Public Event Pages — `EventPageView`, `EventsPageView`, `IndexRedirectView`
  - Enrollment — `SessionEnrollPageView`, `ProposalAcceptPageView`
  - `DesignPageView`, error views
- **`links.db/django/models.py`** is still the real ORM module;
  `links/db/django/repositories/` imports from it
  (`from ludamus.links.db.django.models import ...`). See
  [links-db-layout.md](links-db-layout.md) for the relocation.
- **`adapters/web/django/`** also still owns `forms.py`, `entities.py`,
  `middlewares.py` (`RequestContextMiddleware`, `RedirectErrorMiddleware`,
  still on `request.di.uow.spheres`), `error_views.py`, `design_fixtures.py`,
  `templatetags/tessera/`.
- `INSTALLED_APPS` still references `adapters.web.django.apps.WebMainConfig`
  and `links.db.django.apps.DBMainConfig`.

Already migrated into `gates/`: the whole **Panel** (chronology + multiverse),
**Notice Board / Encounters**, the **CFP** wizard, **Crowd** (both **Auth**
and **Profile**), and anonymous enrollment
(`gates/web/django/chronology/anonymous.py`).

## Done so far

- `gates/web/django/` tree established with `chronology/panel`,
  `multiverse/panel`, `notice_board`, `chronology` (CFP) views and URLs.
- Encounters fully in `gates` + `links` + `mills`/`pacts`.
- Panel views split into one file per area under
  `gates/web/django/chronology/panel/views/`.
- Enrollment slot math (`get_used_slots`, `can_enroll_users`,
  `get_vc_available_slots`) moved out of `links.db/django/models.py` into
  `mills/enrollment.py`, with the ORM query behind
  `EnrollmentParticipationRepositoryProtocol`
  (`links/db/django/enrollment.py`). An `EnrollmentService` now lives on
  `request.services.enrollment`; `SessionEnrollPageView` and
  `create_enrollment_form` run on it and no longer touch `request.di`
  (issue #457, PR-7). The view's transactional enrollment batch
  (`_process_enrollments` and friends) still uses the ORM directly and moves
  into the service together with the view's relocation to `gates/`.
- Crowd / Auth views (`Auth0LoginActionView`, `Auth0LoginCallbackActionView`,
  `Auth0LogoutActionView`, `Auth0LogoutRedirectActionView`,
  `LoginRequiredPageView`) moved into `gates/web/django/crowd/auth.py` with
  URLs under `gates/web/django/crowd/urls.py` (names and paths unchanged).
  The user-provisioning flow now lives in `CrowdAuthService`
  (`mills/crowd.py`, exposed as `request.services.crowd_auth`); the gate
  keeps only OAuth-client, session-login, redirect and message concerns.
- Crowd / Profile views (`ProfilePageView`, `ProfileAvatarPageView`,
  `ProfileShadowbanPageView`, `ProfileConnectedUsersPageView`,
  `ProfileConnectedUserUpdateActionView`,
  `ProfileConnectedUserDeleteActionView`,
  `ProfileConnectedUserClaimLinkActionView`, `ClaimPageView`) moved into
  `gates/web/django/crowd/profile.py`, with `UserForm` / `ConnectedUserForm`
  in `crowd/forms.py` and the routes in `crowd/urls.py` (names and paths
  unchanged). Profile self-service now runs on `ProfileService` and
  connected-user CRUD on `CompanionsService` (`mills/crowd.py`, exposed as
  `request.services.profile` and `request.services.companions`); the
  confirmed-participation count reads through `ProfileStatsRepository`
  (`links/db/django/crowd.py`). No Profile view touches `request.di.uow`
  any more — this completes issue #457's Tier-1 (Crowd on `request.services`)
  (issue #457, PR-4).

## Next step

Migrate the remaining **Public Event Pages** and **Enrollment** views
(`EventPageView`, `EventsPageView`, `IndexRedirectView`,
`SessionEnrollPageView`, `ProposalAcceptPageView`) out of
`adapters/web/django/views.py` into their `gates/web/django/chronology/`
homes, lifting the remaining `request.di.uow` access onto
`request.services`. Anonymous enrollment already moved —
`SessionEnrollmentAnonymousPageView`, `EventAnonymousActivateActionView`,
`AnonymousLoadActionView` and `AnonymousResetActionView` all live in
`gates/web/django/chronology/anonymous.py`. Then relocate the ORM models
(`links/db/django/models.py` → `links/db/django/`) so `adapters/` can be
emptied and locked down with an importlinter contract.

## Definition of done

- `adapters/web/django/views.py` and `models.py` are gone.
- `adapters/` contains nothing importable, and an importlinter contract is
  added forbidding any new `ludamus.adapters` imports (then the package is
  deleted).
- `ROOT_URLCONF` no longer includes `adapters.web.django.urls`.
