# 4. `links/db/django` layout (split fat repositories, relocate models)

**Status:** 🟡 in progress (repository split done; model relocation pending)
**Tracked in TODO:** GLIMPSE ("Split … per GLIMPSE layer rules"),
"Drop HostPersonalData.user FK after 0061 deploys, unify read path"

## Goal

Two related moves inside the persistence adapter:

1. **Relocate ORM models** from `adapters/db/django/models.py` into
   `links/db/django/models.py`, so models live in `links` (their GLIMPSE home)
   and are internal to the package — consumed only through repositories.
2. **Split the fat repository module** once it crosses the 1000-line trigger,
   by aggregate group, behind the package facade.

## Why

The architecture doc ([architecture.md](../agents/architecture.md)) already
describes the target: `links/db/django/{models.py,repositories.py}` behind a
facade `__init__.py`, promoted to `models/` and `repositories/` packages when a
kind crosses ~1000 lines. The repositories are split; the models are still in
`adapters`.

## Current state

- `adapters/db/django/models.py` — still the real ORM module (not yet in
  `links`).
- `links/db/django/repositories/` — package split by aggregate group
  (`multiverse`, `chronology`, `venues`, `sessions`, `submissions`,
  `notice_board`, `discounts`, plus shared `slugs`/`storage` helpers) behind
  a facade `repositories/__init__.py`, so external import paths
  (`from ludamus.links.db.django.repositories import SessionRepository`,
  `from ludamus.links.db.django import repositories`) are unchanged.
- `links/db/django/agenda_item.py`, `schedule_change_log.py` — already
  extracted as per-entity modules (the escape hatch for repos that dwarf the
  rest).
- `links/db/django/uow.py` — `UnitOfWork`, the repo bag (see
  [services-di.md](services-di.md)).

`repositories/` imports models cross-package:
`from ludamus.adapters.db.django.models import (...)`. That import is the seam
the relocation has to cut.

## Done so far

- `agenda_item.py` and `schedule_change_log.py` carved out as per-entity
  modules — the escape hatch for repos that dwarf the rest.
- `repositories.py` promoted to a `repositories/` package halved by aggregate
  group; the facade `repositories/__init__.py` re-exports the public names so
  no import site changed. `SessionRepository` sits in its own `sessions.py`
  (the per-entity escape hatch — it dwarfs the rest of the submissions group).
  The near-identical slug-retry loops (proposal categories, personal/session
  fields, tracks, space tree) were deduplicated into `slugs.py` — pylint's
  cross-module `duplicate-code` check forbids carrying five copies into
  separate files.

## Next step

Relocate the **models** — but only after the `adapters/` views are gone
([glimpse-strangler.md](glimpse-strangler.md)): moving models touches
migrations history and `INSTALLED_APPS`, so it is the last `adapters/db` move,
not the first. When it happens, do it as its own PR: relocate models, flip
`repositories/*` imports to `ludamus.links.db.django.models`, update the
`DBMainConfig` app path.

## Definition of done

- `links/db/django/repositories/` split by aggregate, each part under the
  1000-line trigger, public surface unchanged.
- Models live in `links/db/django/models.py` (or `models/` package); nothing
  imports `ludamus.adapters.db.django.models`.
- `adapters/db/` is empty enough to delete with the rest of `adapters/`.
