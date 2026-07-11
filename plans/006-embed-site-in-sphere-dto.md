# Plan 006: Embed site in SphereDTO and delete read_with_site

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. Your reviewer maintains
> `plans/README.md`; do not edit it.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 8d98755..HEAD -- \
>   src/ludamus/pacts/legacy.py \
>   src/ludamus/pacts/multiverse.py \
>   src/ludamus/links/db/django/repositories/multiverse.py \
>   src/ludamus/mills/multiverse.py \
>   src/ludamus/gates/web/django/context_processors.py
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 003 (merged)
- **Category**: tech-debt
- **Planned at**: commit `8d98755`, 2026-07-10

## Why this matters

Plan 003 added `read_with_site` returning `tuple[SphereDTO, SiteDTO]`.
A follow-up review found the cleaner shape: the sphere repository now
has three methods (`read`, `read_site`, `read_with_site`) that all run
the identical `Sphere.objects.select_related("site").get(id=...)`
query, and the positional tuple is threaded through two protocols and
a service only because `SphereDTO` doesn't carry the site the query
already fetches. Embedding `site: SiteDTO` in `SphereDTO` deletes the
tuple contract and the third method, and fixes a latent bug for free:
`read_site` is the only variant that lets `Sphere.DoesNotExist` escape
raw (a 500) instead of raising the domain `NotFoundError`.

## Current state

- `src/ludamus/pacts/legacy.py:412-418` — `SiteDTO` (fields `domain`,
  `name`, `pk`), defined immediately before `SphereDTO`.
- `src/ludamus/pacts/legacy.py:421-436` — `SphereDTO` has `site_id:
  int` but no `site`; `model_config = ConfigDict(from_attributes=True)`
  so a nested `site: SiteDTO` field validates from the ORM object's
  `sphere.site` attribute with no extra query when `select_related`
  was used.
- `src/ludamus/links/db/django/repositories/multiverse.py` — the three
  query clones:

  ```python
  @staticmethod
  def read_by_domain(domain: str) -> SphereDTO:      # line 43
      try:
          sphere = Sphere.objects.get(site__domain=domain)
      ...
  @staticmethod
  def read(pk: int) -> SphereDTO:                    # line 52
      try:
          sphere = Sphere.objects.select_related("site").get(id=pk)
      except Sphere.DoesNotExist as exception:
          raise NotFoundError from exception

      return SphereDTO.model_validate(sphere)

  @staticmethod
  def read_site(sphere_id: int) -> SiteDTO:          # line 61
      sphere = Sphere.objects.select_related("site").get(id=sphere_id)
      return SiteDTO.model_validate(sphere.site)

  @staticmethod
  def read_with_site(pk: int) -> tuple[SphereDTO, SiteDTO]:  # line 66
      ...
  ```

  Note `read_by_domain` does NOT `select_related("site")` today — it
  must gain it, or the new nested field would lazy-load per call.
- `src/ludamus/pacts/legacy.py:823-827` — `SphereRepositoryProtocol`
  declares `read`, `read_site`, `read_with_site` as `@staticmethod`s.
- `src/ludamus/pacts/multiverse.py:150-154` — `SitesServiceProtocol`
  declares `read_site`, `read_with_site`, `is_manager`,
  `list_spheres`.
- `src/ludamus/mills/multiverse.py:180-190` — `SitesService` has
  pass-throughs `read_site`, `read_with_site`, `is_manager`,
  `list_spheres`.
- `src/ludamus/gates/web/django/context_processors.py:37-59` — the
  only `read_with_site` consumer:

  ```python
  sites_service = request.services.sites
  root_sphere, root_site = sites_service.read_with_site(
      request.context.root_sphere_id
  )
  if request.context.current_sphere_id == request.context.root_sphere_id:
      current_sphere, current_site = root_sphere, root_site
  else:
      current_sphere, current_site = sites_service.read_with_site(
          request.context.current_sphere_id
      )
  ```

- `read_site` callers besides the repo itself:
  `gates/web/django/crowd/auth.py:79`, `:180`, `:310`, `:326` via
  `request.services.sites.read_site(...)` — they stay on `read_site`;
  only its implementation changes.
- `SphereDTO` is constructed exclusively via `model_validate` in the
  repository (verified by grep at planning time); no other layer or
  test builds one directly.
- Exemplar tests: `tests/integration/links/test_sphere_repository.py`
  (has a `TestSphereRepositoryReadWithSite` class from plan 003) and
  `tests/unit/test_sites_mills.py` (stub-repo delegation tests, with a
  `_Spheres` stub exposing `read_site`/`read_with_site`/`is_manager`).
- Environment notes: run `mise trust`, `mise install`,
  `poetry install` first. Bare `mise run` may resolve a global pytest;
  prefix with `PATH="$(pwd)/.venv/bin:$PATH"`. The CI-style gate is
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

- `src/ludamus/pacts/legacy.py`
- `src/ludamus/pacts/multiverse.py`
- `src/ludamus/links/db/django/repositories/multiverse.py`
- `src/ludamus/mills/multiverse.py`
- `src/ludamus/gates/web/django/context_processors.py`
- `tests/integration/links/test_sphere_repository.py`
- `tests/unit/test_sites_mills.py`

**Out of scope** (do NOT touch, even though they look related):

- `gates/web/django/crowd/auth.py` — its `read_site` calls keep
  working; do not migrate them to `.site` access here.
- `current_user()` in the context-processors file — separate change.
- `site_id` on `SphereDTO` — leave it; removing it needs a consumer
  audit that is not this plan.
- `SpherePanelServiceProtocol` / `SpherePanelService` — their `read`
  benefits from the DTO change automatically; no edits needed.

## Git workflow

- Commit style example:
  `refactor(links): embed site in SphereDTO, drop read_with_site`.
- End the commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR.

## Steps

### Step 1: Widen the DTO and fix `read_by_domain`

In `src/ludamus/pacts/legacy.py`, add to `SphereDTO` next to
`site_id`:

```python
site: SiteDTO
```

In `src/ludamus/links/db/django/repositories/multiverse.py`, add
`.select_related("site")` to the `read_by_domain` query so the nested
field never lazy-loads.

**Verify**: `mise run test:py` → all pass (the DTO validates from
`select_related` objects everywhere it is built).

### Step 2: Collapse `read_site`, delete `read_with_site`

In the same repository file:

- Reimplement `read_site` as:

  ```python
  @staticmethod
  def read_site(sphere_id: int) -> SiteDTO:
      return SphereRepository.read(sphere_id).site
  ```

  (This intentionally changes unknown-id behavior from raw
  `Sphere.DoesNotExist` to `NotFoundError` — the domain contract the
  sibling methods already follow.)

- Delete `read_with_site` entirely.

Remove `read_with_site` from `SphereRepositoryProtocol`
(`pacts/legacy.py:827`) and from `SitesServiceProtocol`
(`pacts/multiverse.py:152`). In `mills/multiverse.py`, delete
`SitesService.read_with_site` and add the standard pass-through the
context processor needs instead:

```python
def read(self, sphere_id: int) -> SphereDTO:
    return self._spheres.read(sphere_id)
```

Mirror `read` in `SitesServiceProtocol`.

**Verify**: `grep -rn "read_with_site" src/` → no matches.

### Step 3: Rewrite the context processor consumer

In `gates/web/django/context_processors.py`, replace the
`read_with_site` calls:

```python
sites_service = request.services.sites
root_sphere = sites_service.read(request.context.root_sphere_id)
if request.context.current_sphere_id == request.context.root_sphere_id:
    current_sphere = root_sphere
else:
    current_sphere = sites_service.read(request.context.current_sphere_id)
```

and return `root_site=root_sphere.site`,
`current_site=current_sphere.site`. Keep the `is_manager` logic and
the `SitesContextData` keys exactly as they are.

**Verify**: `mise run test:py` → all pass.

### Step 4: Update the tests

- In `tests/integration/links/test_sphere_repository.py`, replace
  `TestSphereRepositoryReadWithSite` with a `TestSphereRepositoryRead`
  class asserting: `read(...)` returns a DTO whose `.site` equals
  `SiteDTO.model_validate(sphere.site)`; `read` raises `NotFoundError`
  for an unknown pk; `read` issues exactly one query
  (`django_assert_num_queries(1)`). Add a
  `TestSphereRepositoryReadSite` test asserting `read_site` now raises
  `NotFoundError` for an unknown pk (the bug this plan fixes).
- In `tests/unit/test_sites_mills.py`, update the `_Spheres` stub:
  drop `read_with_site`, add `read`; replace the `read_with_site`
  delegation test with a `read` delegation test; keep the
  `is_manager` and `read_site` tests working.

**Verify**: `mise run test:unit` → all pass;
`mise run test:py` → all pass.

### Step 5: Full gate

**Verify**: `mise run check` → exit 0 (mypy strict, import-linter
7/7, vulture, pylint) and `mise run test:py` → all pass.

## Test plan

- Repository: `read` returns embedded site, single query,
  `NotFoundError` on unknown pk; `read_site` raises `NotFoundError`
  on unknown pk (regression for the fixed 500 path).
- Unit: `SitesService.read` delegation; existing `read_site` /
  `is_manager` / `list_spheres` tests stay green.
- Whole suite guards the context-processor rewrite (every rendered
  page exercises it).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -rn "read_with_site" src/ tests/` returns no matches
- [ ] `grep -c "select_related" src/ludamus/links/db/django/repositories/multiverse.py`
  returns 3 (list_all, read_by_domain, read)
- [ ] `mise run test:py` exits 0, including the reworked tests
- [ ] `mise run check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts no longer match the live code (drift).
- Grep finds `SphereDTO(` constructed directly (not `model_validate`)
  anywhere outside the repository — the required `site` field would
  break it; report the call site.
- Any test asserts that `read_site` raises `Sphere.DoesNotExist` —
  that means the old behavior is load-bearing; report.
- mypy or import-linter failures whose fix requires touching files
  outside the in-scope list.

## Maintenance notes

- `site_id` on `SphereDTO` is now redundant with `site.pk`; removing
  it is a small follow-up needing a template/consumer audit.
- If a future caller needs spheres in bulk, mirror the embedded-site
  pattern with `select_related` on the queryset — never per-row
  `read_site` calls.
- Reviewers should scrutinize: no template or view depended on
  `read_site` raising `DoesNotExist`, and `read_by_domain` gained
  `select_related` (middleware calls it per request).
