# 4. `links/db/django` layout (split fat repositories, relocate models)

**Status:** 🔴 not started (one-off extractions aside)
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
kind crosses ~1000 lines. Today the models are still in `adapters`, and
`repositories.py` is well past the trigger but unsplit.

## Current state

- `adapters/db/django/models.py` — still the real ORM module (not yet in
  `links`).
- `links/db/django/repositories.py` — one module holding all repository
  classes; **well past the ~1000-line split trigger** and unsplit.
- `links/db/django/agenda_item.py`, `schedule_change_log.py` — already
  extracted as per-entity modules (the escape hatch for repos that dwarf the
  rest).
- `links/db/django/uow.py` — `UnitOfWork`, the repo bag (see
  [services-di.md](services-di.md)).

`repositories.py` imports models cross-package:
`from ludamus.adapters.db.django.models import (...)`. That import is the seam
the relocation has to cut.

## Done so far

- `agenda_item.py` and `schedule_change_log.py` carved out as per-entity
  modules — the escape hatch for repos that dwarf the rest.
- `links/db/django/__init__.py` facade exists as the public import surface.

## Next step

Split **`repositories.py`** (well past the split trigger) without moving models
yet — it is the highest-friction file and the split is mechanical:

1. Promote `repositories.py` → `repositories/` package; keep the facade one
   level up in `links/db/django/__init__.py` so external import paths
   (`from ludamus.links.db.django import SessionRepository`) don't change.
2. Halve by aggregate group (don't shard): e.g. `submissions.py` (sessions,
   proposals, categories, fields, requirements, facilitators), `chronology.py`
   (events, agenda, enrollment), `venues.py` (venue/area/space/track/timeslot),
   `crowd.py` (users, connected users, spheres). Arrange parts so they don't
   create circular imports.
3. Run importlinter + tests after each halving.

Defer the **model relocation** until after the repo split and after the
`adapters/` views are gone ([glimpse-strangler.md](glimpse-strangler.md)) —
moving models touches migrations history and `INSTALLED_APPS`, so it is the
last `adapters/db` move, not the first. When it happens, do it as its own PR:
relocate models, flip `repositories/*` imports to `ludamus.links.db.django.models`,
update the `DBMainConfig` app path.

## Definition of done

- `links/db/django/repositories/` split by aggregate, each part under the
  1000-line trigger, public surface unchanged.
- Models live in `links/db/django/models.py` (or `models/` package); nothing
  imports `ludamus.adapters.db.django.models`.
- `adapters/db/` is empty enough to delete with the rest of `adapters/`.
