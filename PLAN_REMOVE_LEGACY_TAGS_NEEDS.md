# PLAN — Remove legacy Tag/needs/requirements + rename HostPersonalData

Branch: `remove-legacy-tags-needs-fields`

## Goal

Retire five legacy database artifacts and rename one model:

- `Tag`, `TagCategory` (+ M2M `Session.tags`, `Event.filterable_tag_categories`,
  `ProposalCategory.tag_categories` and their through-tables)
- `Session.needs`, `Session.requirements`
- `HostPersonalData.user` (dead FK + its unique/check constraints)
- Rename model `HostPersonalData` → `PersonalDataFieldValue`

## Deployment model — single deploy

Production deploys are `docker-compose down` → `up`: **full downtime, no old/new
code overlap.** So there is no rolling-deploy hazard and **no need for
`SeparateDatabaseAndState`** — plain `RemoveField` / `DeleteModel` in one deploy.

The one ordering rule that still matters is *inside* the migration graph: the
data migration must run **before** the schema-drop migration. Data migrations use
the **historical** model (`apps.get_model`), frozen at their graph position — not
`models.py` — so the `needs`/`requirements` columns still exist and are readable
when the data migration runs, even though `models.py` has already dropped the
fields. Migration `B` (drop) `dependencies` on migration `A` (data) guarantees the
order.

## Findings that shape the plan

- **Tags are already migrated.** Migration `0059` copied every `TagCategory` →
  public `SessionField`, `Tag` → `SessionFieldOption`, and `Session.tags` →
  `SessionFieldValue`. Every live caller of `sessions.create` passes
  `tag_ids=[]`, and `read_tags` / `read_tag_categories` have no live callers.
  **No tag data migration is needed — delete only.**
- **needs/requirements have no migration** → new data migration into **secret**
  (`is_public=False`) TEXT `SessionField`s.
- **`HostPersonalData.user` is a dead FK** — every write path uses
  `facilitator_id`. Dropping it requires first dropping the constraints
  `unique_personal_data_per_user_event_field` and `personal_data_requires_owner`.

## Resolved decisions

1. **Secret field labels** — Polish: **"Zapotrzebowanie"** (needs),
   **"Wymagania"** (requirements).
2. **Archival only** — these are past events. Copy values into secret
   `SessionFieldValue`s; **no** `SessionFieldRequirement` wiring (fields do not
   reappear as editable).
3. **No seamless-deploy risk** — downtime deploy, so write-loss window is moot.
4. **Rename the physical table too** — `db_table` becomes
   `personal_data_field_value`, matching `session_field_value`. Downtime makes
   the `ALTER TABLE RENAME` safe.

Migration numbers are placeholders (`00XX`); real numbers come from
`mise run dj makemigrations`. The tree has two leaf `0099` migrations —
reconcile with a merge migration if `makemigrations` reports a conflict.

---

## Steps

### Step 1 — Rename `HostPersonalData` → `PersonalDataFieldValue`

- Rename the class; update every import/reference across `models`, `admin`,
  repositories, `mills/legacy`, `mills/submissions`, `pacts`, `inits`.
- Set `db_table = "personal_data_field_value"`.
- `mise run dj makemigrations` → `RenameModel` + `AlterModelTable`.
- Verify: `mise run check` + `mise run test`.

### Step 2 — Data migration: needs/requirements → secret SessionFields

- New `RunPython` migration `00XX_migrate_needs_requirements_to_fields`.
- Per event with ≥1 session holding non-empty `needs`/`requirements`: create a
  TEXT `SessionField` ("Zapotrzebowanie" / "Wymagania", `is_multiple=False`,
  `is_public=False`), reusing `0059`'s slug-dedup loop; copy each session's
  non-empty text into a `SessionFieldValue`. No `SessionFieldRequirement`.
- `reverse_code=migrations.RunPython.noop`.
- Verify: migration test asserting a non-empty `needs`/`requirements` lands as a
  secret `SessionFieldValue` and empty values create nothing; `mise run test`.

### Step 3 — Remove all app references to the doomed fields

By symbol:

- **Models**: `Session.needs`, `Session.requirements`, `Session.tags`,
  `Event.filterable_tag_categories`, `ProposalCategory.tag_categories`,
  `PersonalDataFieldValue.user` and its two `user`-referencing constraints;
  adjust `personal_data_requires_owner`.
- **Admin**: `Tag`, `TagCategory` registrations.
- **DTOs** (`pacts/legacy.py`): `TagDTO`, `TagCategoryDTO`,
  `PendingSessionTagDTO`, and the `needs`/`requirements` DTO fields.
- **Repositories**: `read_tags`, `read_tag_categories`, `read_tag_ids`, the
  pending-session tags read, the `tag_ids` param + `session.tags.set` in
  `SessionRepository.create`, and `needs`/`requirements` in the session read.
- **Views**: chronology session view + panel `proposals` view `needs`/
  `requirements` handling; the `filterable_tag_categories` context key path;
  `entities.public_tag_categories`.
- **Forms**: the `needs` field on the facilitator self-edit form;
  `cfp_tags` "needs" label.
- **Change-log**: `needs`/`requirements` comparisons in `mills/chronology`.
- **Templates**: proposal detail/edit/create, facilitator-detail, chronology
  templates rendering tags/needs/requirements.
- **TS client**: tag-category branches in `session-filters.ts`.
- Verify after each cohesive chunk: `mise run check` + `mise run test`.

### Step 4 — Schema-drop migration

Precondition (user checks production before deploying): no `host_personal_data`
row is user-only.

```sql
SELECT count(*) FROM host_personal_data
WHERE user_id IS NOT NULL AND facilitator_id IS NULL;  -- must be 0
```

- New migration `00XX_drop_legacy_columns_tables`, `dependencies` on the Step-2
  data migration:
  - Drop `unique_personal_data_per_user_event_field`,
    `personal_data_requires_owner`, then `RemoveField` `user`.
  - `RemoveField` `Session.needs`, `Session.requirements`.
  - `RemoveField` the three M2M fields; `DeleteModel` `Tag`, then `TagCategory`
    (Django emits the through-table + FK-ordered drops).
- Plain operations — no `SeparateDatabaseAndState`.
- Verify: `mise run test`; smoke via `mise run start` + `mise run shots`
  (proposal list/detail/edit, event page filters, facilitator personal-data edit).

---

## Rollback

Single deploy — roll back by redeploying the previous image and restoring the DB
from the pre-deploy backup. The schema drop is destructive; the Step-2 data
migration is additive (its noop reverse leaves the secret fields, which is
harmless). Take a DB backup before the deploy.

## Quality gates (every step)

- [ ] `mise run check` (format + lint) passes
- [ ] `mise run test` passes
- [ ] No new `noqa` / `type: ignore` without per-case approval
- [ ] Commit on `remove-legacy-tags-needs-fields`
