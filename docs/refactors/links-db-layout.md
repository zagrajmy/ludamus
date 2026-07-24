# 4. `links/db/django` layout (split fat repositories, relocate models)

**Status:** ✅ done

## Goal

Two related moves inside the persistence adapter:

1. **Relocate ORM models** from `adapters/db/django/models.py` into
   `links/db/django/models.py`, so models live in `links` (their GLIMPSE home)
   and are internal to the package — consumed only through repositories.
2. **Split the fat repository module** once it crosses the 1000-line trigger,
   by aggregate group, behind the package facade.

## Why

The architecture doc ([architecture.md](../agents/architecture.md)) describes
the target: `links/db/django/{models.py,repositories.py}` behind a facade
`__init__.py`, promoted to `models/` and `repositories/` packages when a kind
crosses ~1000 lines.

## What landed

- `agenda_item.py` and `schedule_change_log.py` carved out as per-entity
  modules — the escape hatch for repos that dwarf the rest.
- `repositories.py` promoted to a `repositories/` package halved by aggregate
  group (`multiverse`, `chronology`, `venues`, `sessions`, `submissions`,
  `notice_board`, `discounts`, plus shared `slugs`/`storage` helpers). The
  facade `repositories/__init__.py` re-exports the public names, so no import
  site changed. `SessionRepository` sits in its own `sessions.py` (the
  per-entity escape hatch — it dwarfs the rest of the submissions group). The
  near-identical slug-retry loops (proposal categories, personal/session
  fields, tracks, space tree) were deduplicated into `slugs.py` — pylint's
  cross-module `duplicate-code` check forbids carrying five copies into
  separate files.
- The whole `adapters/db/` package moved to `links/db/`: models, migrations,
  admin, the per-entity repo modules and `uow.py`. `INSTALLED_APPS` now
  references `ludamus.links.db.django.apps.DBMainConfig`; every import site
  points at `ludamus.links.db.django.*`. `adapters/db/` is gone.

## Follow-up (not blocking)

`repositories/submissions.py` sits just over the ~1000-line trigger. Halve it
along the aggregate seam the next time it is touched.
