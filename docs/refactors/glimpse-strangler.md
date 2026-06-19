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
  - Auth — `Auth0LoginActionView`, `Auth0LoginCallbackActionView`,
    `Auth0LogoutActionView`, `Auth0LogoutRedirectActionView`,
    `LoginRequiredPageView` (Crowd)
  - Profile — `ProfilePageView`, `ProfileConnectedUsersPageView`,
    `ProfileConnectedUserUpdateActionView`,
    `ProfileConnectedUserDeleteActionView`, `ProfileAvatarPageView` (Crowd)
  - Public Event Pages — `EventPageView`, `EventsPageView`, `IndexRedirectView`
  - Enrollment — `SessionEnrollPageView`,
    `SessionEnrollmentAnonymousPageView`, `ProposalAcceptPageView`,
    `EventAnonymousActivateActionView`, `AnonymousLoadActionView`,
    `AnonymousResetActionView`
  - `DesignPageView`, error views
- **`adapters/db/django/models.py`** is still the real ORM module;
  `links/db/django/repositories.py` imports from it
  (`from ludamus.adapters.db.django.models import ...`). See
  [links-db-layout.md](links-db-layout.md) for the relocation.
- **`adapters/web/django/`** also still owns `forms.py`, `entities.py`,
  `middlewares.py` (`RequestContextMiddleware`, `RedirectErrorMiddleware`,
  still on `request.di.uow.spheres`), `error_views.py`, `design_fixtures.py`,
  `templatetags/tessera/`.
- `INSTALLED_APPS` still references `adapters.web.django.apps.WebMainConfig`
  and `adapters.db.django.apps.DBMainConfig`.

Already migrated into `gates/`: the whole **Panel** (chronology + multiverse),
**Notice Board / Encounters**, and the **CFP** wizard.

## Done so far

- `gates/web/django/` tree established with `chronology/panel`,
  `multiverse/panel`, `notice_board`, `chronology` (CFP) views and URLs.
- Encounters fully in `gates` + `links` + `mills`/`pacts`.
- Panel views split into one file per area under
  `gates/web/django/chronology/panel/views/`.

## Next step

Migrate the **Crowd / Auth** views (`Auth0LoginActionView`,
`Auth0LoginCallbackActionView`, `Auth0LogoutActionView`,
`Auth0LogoutRedirectActionView`, `LoginRequiredPageView`) out of
`adapters/web/django/views.py` into `gates/web/django/crowd/`:

1. Create `gates/web/django/crowd/{views.py,urls.py}` and a `crowd` namespace.
2. Move the views; replace any `request.di.uow` access per
   [services-di.md](services-di.md) (do both angles in the same move).
3. Point `gates/web/django/urls.py` at the new `crowd` include; drop the old
   routes from `adapters/web/django/urls.py`.
4. Move the auth integration tests alongside; run `mise run test`.

Auth is a good first slice: it is self-contained, has no template-heavy
surface, and forces the `crowd` package to exist (Profile follows into the
same package next).

## Definition of done

- `adapters/web/django/views.py` and `models.py` are gone.
- `adapters/` contains nothing importable, and an importlinter contract is
  added forbidding any new `ludamus.adapters` imports (then the package is
  deleted).
- `ROOT_URLCONF` no longer includes `adapters.web.django.urls`.
