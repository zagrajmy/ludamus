# Plan 009: Stop defeating the options prefetch with in-loop order_by

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. Your reviewer maintains
> `plans/README.md`; do not edit it.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 7ffe8ba..HEAD -- \
>   src/ludamus/links/db/django/repositories/submissions.py \
>   tests/integration/links/test_proposal_category_repository.py
> ```
>
> If either file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `7ffe8ba`, 2026-07-10

## Why this matters

`ProposalCategoryRepository.list_personal_field_requirements` and
`list_session_field_requirements` prefetch `field__options` and then
iterate `field.options.all().order_by("order", "label")` per field.
Calling `.order_by()` on a prefetched relation clones a fresh
queryset and ignores the prefetch cache, so every field costs one
extra query — the prefetch is pure overhead today. Moving the
ordering into a `Prefetch` object restores one query for all options
regardless of field count, with identical output (the option models'
default `Meta.ordering` is already `["order", "label"]`).

## Current state

- `src/ludamus/links/db/django/repositories/submissions.py:439-476`
  — `list_personal_field_requirements`:

  ```python
  requirements = (
      PersonalDataFieldRequirement.objects.filter(
          category_id=category_id
      )
      .select_related("field")
      .prefetch_related("field__options")
      .order_by("order", "field__name")
  )
  result = []
  for req in requirements:
      field = req.field
      options = [
          PersonalDataFieldOptionDTO.model_validate(o)
          for o in field.options.all().order_by("order", "label")
      ]
  ```

  (The outer `.order_by("order", "field__name")` on `requirements`
  is fine — it orders the base queryset, not a prefetched cache.
  Leave it alone.)
- `src/ludamus/links/db/django/repositories/submissions.py:478-514`
  — `list_session_field_requirements`: same shape with
  `SessionFieldRequirement`, `SessionFieldOptionDTO`, and the same
  `field.options.all().order_by("order", "label")` at line 493.
- These are the ONLY two prefetch-defeating sites.
  `grep -n 'order_by("order", "label")' -r src/` returns exactly
  lines 454 and 493 of this file at the planned-at commit. The
  other option prefetches in the same file (`list_by_event`,
  `read_by_slug`, `update` → `_to_dto` at lines 677 and 827) iterate
  `field.options.all()` **without** `.order_by()`, so they already
  use the cache and the models' default ordering — do not touch
  them.
- `src/ludamus/adapters/db/django/models.py:1230-1232` and
  `:1367-1369` — `PersonalDataFieldOption.Meta.ordering` and
  `SessionFieldOption.Meta.ordering` are both
  `ClassVar = ["order", "label"]`. The in-loop `.order_by()` is
  therefore redundant for ordering; its only effect is defeating
  the cache. The explicit `Prefetch` queryset below keeps the
  intent visible and immune to future `Meta.ordering` edits.
- Both option models are already imported at
  `src/ludamus/links/db/django/repositories/submissions.py:13` and
  `:18`; `django.db.models` imports on line 3 currently pull
  `Count, Max, Q` — `Prefetch` must be added there.
- Callers (behavior contract): only
  `src/ludamus/mills/legacy.py:279` and `:286`, thin service
  pass-throughs of the returned DTO lists. No caller depends on any
  other ordering.
- Existing test file to extend:
  `tests/integration/links/test_proposal_category_repository.py`
  (currently covers `get_or_create_by_slug` only). Query-count
  assertion pattern:
  `tests/integration/links/test_sphere_repository.py:26-28`.
- Repo conventions that apply: no docstrings; NEVER add
  noqa/type-ignore/pylint directives; `links` code → integration
  tests; in tests never use `ANY` for simple values.
- Environment notes: `export MISE_ENV=sandbox` for all mise commands
  in this container, and run `mise install && poetry install` first.
  Prefix test/check runs with `PATH="$(pwd)/.venv/bin:$PATH"`
  because a global pytest shadows the venv. The CI-style gate is
  `mise run check` (there is no `prcheck` task).

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise install && poetry install` | exit 0 |
| All Py tests | `mise run test:py` | all pass |
| Unit tests | `mise run test:unit` | all pass |
| CI-style checks | `mise run check` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/links/db/django/repositories/submissions.py`
- `tests/integration/links/test_proposal_category_repository.py`

**Out of scope** (do NOT touch, even though they look related):

- `_to_dto`, `list_by_event`, `read_by_slug`, `update` in the same
  file — their bare `options.all()` already uses the prefetch cache.
- `src/ludamus/adapters/db/django/models.py` — the `Meta.ordering`
  definitions stay as they are.
- `src/ludamus/mills/legacy.py` — pass-through callers, unaffected.

## Git workflow

- Commit style example:
  `perf(links): order option prefetch once, use the cache`.
- End the commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR.

## Steps

### Step 1: Move the ordering into the prefetch at both sites

In `src/ludamus/links/db/django/repositories/submissions.py`:

1. Extend the django imports on line 3:

   ```python
   from django.db.models import Count, Max, Prefetch, Q
   ```

2. In `list_personal_field_requirements`, replace
   `.prefetch_related("field__options")` with:

   ```python
   .prefetch_related(
       Prefetch(
           "field__options",
           queryset=PersonalDataFieldOption.objects.order_by(
               "order", "label"
           ),
       )
   )
   ```

   and change the loop to iterate the cache:

   ```python
   options = [
       PersonalDataFieldOptionDTO.model_validate(o)
       for o in field.options.all()
   ]
   ```

3. In `list_session_field_requirements`, do the same with
   `SessionFieldOption.objects.order_by("order", "label")` and drop
   its in-loop `.order_by("order", "label")`.

Do not touch the outer `.order_by("order", "field__name")` on
either `requirements` queryset.

**Verify**:

```sh
grep -n 'options.all().order_by' \
  src/ludamus/links/db/django/repositories/submissions.py
```

→ no matches; then `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py`
→ all pass.

### Step 2: Add ordering and query-count integration tests

Extend
`tests/integration/links/test_proposal_category_repository.py`
with two classes, one per method (imports: the models
`PersonalDataField`, `PersonalDataFieldOption`,
`PersonalDataFieldRequirement`, `SessionField`, `SessionFieldOption`,
`SessionFieldRequirement` from `ludamus.links.db.django.models`;
`ProposalCategoryFactory` from `tests.integration.conftest`).

Arrange recipe (mirror for the session variant):

```python
category = ProposalCategoryFactory()
field = PersonalDataField.objects.create(
    event=category.event,
    name="Diet",
    question="Diet?",
    slug="diet",
    field_type="select",
)
PersonalDataFieldOption.objects.create(
    field=field, label="Zeta", value="z", order=0
)
PersonalDataFieldOption.objects.create(
    field=field, label="Beta", value="b", order=1
)
PersonalDataFieldOption.objects.create(
    field=field, label="Alpha", value="a", order=1
)
PersonalDataFieldRequirement.objects.create(
    category=category, field=field
)
```

Cases per class:

- ordering: with the out-of-insertion-order options above, assert
  `[o.label for o in result[0].field.options] ==
  ["Zeta", "Alpha", "Beta"]` — `order` wins, `label` breaks the
  tie.
- constant queries: 2 fields × 2 options each (each field with its
  own requirement), then

  ```python
  with django_assert_num_queries(2):
      ProposalCategoryRepository.list_personal_field_requirements(
          category.pk
      )
  ```

  1 query for requirements + fields (`select_related`), 1 for all
  options (the prefetch). Before this plan the same arrange cost 4.

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all
pass, including the 4 new tests.

### Step 3: Full gate

**Verify**: `PATH="$(pwd)/.venv/bin:$PATH" mise run check` → exit 0
and `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` → all pass.

## Test plan

- New integration tests (links code → integration tests, per
  `docs/TESTING_STRATEGY.md`) in
  `tests/integration/links/test_proposal_category_repository.py`,
  modeled structurally on the existing classes in that file:
  - `TestListPersonalFieldRequirements`: options ordered by
    `(order, label)`; `django_assert_num_queries(2)` for 2 fields ×
    2 options.
  - `TestListSessionFieldRequirements`: same two cases for the
    session-field variant.
- Existing suite guards the DTO shape: proposal pages render these
  DTOs, so `mise run test:py` passing unmodified proves behavior
  parity.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c 'order_by("order", "label")'` over
  `src/ludamus/links/db/django/repositories/submissions.py` returns
  `2`, and both matches sit inside `Prefetch(...)` querysets
  (`grep -n -B 2` to confirm)
- [ ] `grep -c 'options.all().order_by'` over
  `src/ludamus/links/db/django/repositories/submissions.py` returns
  `0`
- [ ] `PATH="$(pwd)/.venv/bin:$PATH" mise run test:py` exits 0,
  including the 4 new tests
- [ ] `PATH="$(pwd)/.venv/bin:$PATH" mise run check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts no longer match the live code (drift), or grep finds
  `order_by("order", "label")` at sites other than lines ~454 and
  ~493 of `submissions.py` — this plan covers exactly two sites; a
  third means the codebase moved.
- Either option model's `Meta.ordering` is no longer
  `["order", "label"]` — the "identical output" claim would need
  re-verification.
- Any test fails because a call site expected unordered or
  differently-ordered options.
- The query-count test cannot reach 2 queries without touching an
  out-of-scope file.

## Maintenance notes

- If anyone later adds `.filter()`/`.order_by()` on a prefetched
  `field.options` inside a loop, the query-count tests added here
  will catch it — that is their main job; keep the pinned `2`.
- The `_to_dto` paths (lines ~677 and ~827) rely on `Meta.ordering`
  for their option order; if a product change ever demands a
  different order there, use the same `Prefetch` pattern rather
  than an in-loop `.order_by()`.
- Reviewers should scrutinize: the outer
  `.order_by("order", "field__name")` on the requirements querysets
  was NOT removed (it orders the fields themselves), and no
  behavioral change leaked into the DTOs.
