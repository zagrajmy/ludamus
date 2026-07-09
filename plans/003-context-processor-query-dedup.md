# Plan 003: Halve the sphere/site queries in the sites context processor

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 0bec0f2..HEAD -- \
>   src/ludamus/gates/web/django/context_processors.py \
>   src/ludamus/mills/multiverse.py \
>   src/ludamus/pacts/multiverse.py \
>   src/ludamus/pacts/legacy.py \
>   src/ludamus/links/db/django/repositories/multiverse.py
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `0bec0f2`, 2026-07-09

## Why this matters

The `sites` context processor runs on **every** template-rendering
request. It fetches the root sphere and current sphere (each query
already `select_related("site")`), then calls `read_site` twice — which
re-fetches the exact same sphere+site rows a second time. That is four
queries where one or two suffice, paid on every page view. On the main
domain (root sphere == current sphere) all four hit the same row. The
fix also moves this context processor from the legacy `request.di.uow`
surface onto `request.services`, which repo rules require for changed
code (`CLAUDE.md`: "New code must use `request.services`; never extend
the `request.di.uow` surface").

## Current state

- `src/ludamus/gates/web/django/context_processors.py:37-52` — the
  duplication:

  ```python
  sphere_repository = request.di.uow.spheres
  root_sphere = sphere_repository.read(request.context.root_sphere_id)
  current_sphere = sphere_repository.read(
      request.context.current_sphere_id
  )

  is_sphere_manager = False
  if request.user.is_authenticated and request.context.current_user_slug:
      is_sphere_manager = sphere_repository.is_manager(
          current_sphere.pk, request.context.current_user_slug
      )

  return SitesContextData(
      root_site=sphere_repository.read_site(root_sphere.pk),
      current_site=sphere_repository.read_site(current_sphere.pk),
      current_sphere=current_sphere,
      is_sphere_manager=is_sphere_manager,
  )
  ```

  (Note: in the live file the `read` calls at lines 38-39 are
  single-line; the excerpt is wrapped for line length only.)

- `src/ludamus/links/db/django/repositories/multiverse.py:51-63` — both
  repo methods run the same query:

  ```python
  @staticmethod
  def read(pk: int) -> SphereDTO:
      try:
          sphere = Sphere.objects.select_related("site").get(id=pk)
      except Sphere.DoesNotExist as exception:
          raise NotFoundError from exception

      return SphereDTO.model_validate(sphere)

  @staticmethod
  def read_site(sphere_id: int) -> SiteDTO:
      sphere = Sphere.objects.select_related("site").get(id=sphere_id)
      return SiteDTO.model_validate(sphere.site)
  ```

- `src/ludamus/pacts/legacy.py:818-830` — `SphereRepositoryProtocol`
  declares `read`, `read_site`, `is_manager`, etc. as `@staticmethod`s.
- `src/ludamus/pacts/legacy.py:412-417` — `SiteDTO` (fields: `domain`,
  `name`, `pk`); `SphereDTO` follows at line 420.
- `src/ludamus/mills/multiverse.py:171-184` — `SitesService`, already
  exposed as `request.services.sites` (`inits/services.py:166`):

  ```python
  class SitesService:
      def __init__(
          self,
          spheres: SphereRepositoryProtocol,
          directory: SphereDirectoryRepositoryProtocol,
      ) -> None:
          self._spheres = spheres
          self._directory = directory

      def read_site(self, sphere_id: int) -> SiteDTO:
          return self._spheres.read_site(sphere_id)

      def list_spheres(self) -> list[SphereListItemDTO]:
          return self._directory.list_all()
  ```

- `src/ludamus/pacts/multiverse.py:150-152` — `SitesServiceProtocol`
  declares `read_site` and `list_spheres`.
- `read_site` has other callers (`gates/web/django/crowd/auth.py:79`,
  `:180`, `:310`, `:326` via `request.services.sites`) — it must stay.
- The context processor already uses `request.services` elsewhere:
  `context_processors.py:87` calls
  `request.services.notifications.get_navbar(...)`.
- Conventions: repos return Pydantic DTOs, never models; protocol
  methods on this repo are `@staticmethod`; functions with 3+
  parameters take keyword-only args (not triggered here — new method
  has one parameter).
- Exemplar tests: `tests/integration/links/test_sphere_repository.py`
  (repository), `tests/unit/test_sites_mills.py` (SitesService unit
  test with a stub repo).

## Commands you will need

| Purpose         | Command                          | Expected on success |
|-----------------|----------------------------------|---------------------|
| Install         | `mise install && poetry install` | exit 0              |
| All Py tests    | `mise run test:py`               | all pass            |
| One test file   | `mise run test:int -- <path>`    | all pass            |
| Unit tests      | `mise run test:unit`             | all pass            |
| CI-style checks | `mise run check`                 | exit 0              |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/pacts/legacy.py` (add one protocol method)
- `src/ludamus/pacts/multiverse.py` (extend `SitesServiceProtocol`)
- `src/ludamus/links/db/django/repositories/multiverse.py`
- `src/ludamus/mills/multiverse.py`
- `src/ludamus/gates/web/django/context_processors.py`
- `tests/integration/links/test_sphere_repository.py`
- `tests/unit/test_sites_mills.py`

**Out of scope** (do NOT touch, even though they look related):

- `current_user()` in the same context-processors file — it still uses
  `request.di.uow.active_users`; migrating it is a separate change.
- `read_site` and its callers in `gates/web/django/crowd/auth.py`.
- `inits/` DI wiring — `SitesService` already receives the spheres
  repo; no registry change is needed.

## Git workflow

- Branch off the default branch; commit style example:
  `perf(web): fetch sphere+site once in the sites context processor`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add `read_with_site` to the repository

In `src/ludamus/links/db/django/repositories/multiverse.py`, next to
`read`, add:

```python
@staticmethod
def read_with_site(pk: int) -> tuple[SphereDTO, SiteDTO]:
    try:
        sphere = Sphere.objects.select_related("site").get(id=pk)
    except Sphere.DoesNotExist as exception:
        raise NotFoundError from exception

    return (
        SphereDTO.model_validate(sphere),
        SiteDTO.model_validate(sphere.site),
    )
```

Declare it in `SphereRepositoryProtocol`
(`src/ludamus/pacts/legacy.py:818`), matching the surrounding
`@staticmethod` style:

```python
@staticmethod
def read_with_site(pk: int) -> tuple[SphereDTO, SiteDTO]: ...
```

**Verify**: `mise run test:py` → all pass (nothing consumes it yet).

### Step 2: Expose it on `SitesService`, plus `is_manager`

In `src/ludamus/mills/multiverse.py`, add to `SitesService`:

```python
def read_with_site(self, sphere_id: int) -> tuple[SphereDTO, SiteDTO]:
    return self._spheres.read_with_site(sphere_id)

def is_manager(self, sphere_id: int, user_slug: str) -> bool:
    return self._spheres.is_manager(sphere_id, user_slug)
```

Mirror both in `SitesServiceProtocol`
(`src/ludamus/pacts/multiverse.py:150-152`). Import `SphereDTO` where
needed following the file's existing import style.

**Verify**: `mise run test:unit` → all pass.

### Step 3: Rewrite the `sites` context processor

In `src/ludamus/gates/web/django/context_processors.py`, replace the
body of `sites()` after the early-return guard with logic that:

1. Uses `request.services.sites` (not `request.di.uow.spheres`).
2. Calls `read_with_site` once for the root sphere.
3. Reuses the root result when
   `request.context.current_sphere_id == request.context.root_sphere_id`
   (the main-domain case), otherwise calls `read_with_site` for the
   current sphere.
4. Keeps the `is_manager` call semantics identical, now via
   `request.services.sites.is_manager(...)`.

Target shape:

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

is_sphere_manager = False
if request.user.is_authenticated and request.context.current_user_slug:
    is_sphere_manager = sites_service.is_manager(
        current_sphere.pk, request.context.current_user_slug
    )

return SitesContextData(
    root_site=root_site,
    current_site=current_site,
    current_sphere=current_sphere,
    is_sphere_manager=is_sphere_manager,
)
```

Update imports/TYPE_CHECKING as the type checker requires.

**Verify**: `mise run test:py` → all pass (template-rendering
integration tests such as `tests/integration/web/test_index_page.py`
exercise the context processor on every page).

### Step 4: Tests for the new surface

- In `tests/integration/links/test_sphere_repository.py`, add a class
  for `read_with_site`: returns matching `SphereDTO`/`SiteDTO` for an
  existing sphere; raises `NotFoundError` for an unknown pk; and issues
  exactly one query — use pytest-django's `django_assert_num_queries`
  fixture:

  ```python
  def test_single_query(self, sphere, django_assert_num_queries):
      with django_assert_num_queries(1):
          SphereRepository.read_with_site(sphere.pk)
  ```

- In `tests/unit/test_sites_mills.py`, extend the existing stub-repo
  pattern to cover `SitesService.read_with_site` and
  `SitesService.is_manager` delegation.

**Verify**:
`mise run test:int -- tests/integration/links/test_sphere_repository.py`
→ all pass; `mise run test:unit` → all pass.

### Step 5: Full gate

**Verify**: `mise run check` → exit 0 (this runs the import-linter
contracts — pacts/mills/links/gates layering must hold — plus mypy
strict, vulture, and the rest), and `mise run test:py` → all pass.

## Test plan

- Repository: `read_with_site` happy path, `NotFoundError`, and the
  single-query assertion (the regression this plan exists for) — in
  `tests/integration/links/test_sphere_repository.py`, modeled on its
  existing classes.
- Unit: `SitesService.read_with_site` / `is_manager` delegation in
  `tests/unit/test_sites_mills.py`, modeled on its existing stub test.
- Existing page-render integration tests cover the context processor
  end to end.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -c "read_site\|di.uow" src/ludamus/gates/web/django/context_processors.py`
  returns 0
- [ ] `mise run test:py` exits 0, including the new repo and unit tests
- [ ] `mise run check` exits 0 (import-linter, mypy, vulture all
  green)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts in "Current state" no longer match the live code
  (drift).
- `request.services.sites` turns out not to be reachable from the
  context processor's request object (it is per
  `context_processors.py:87`, but if middleware ordering says
  otherwise, report).
- vulture or import-linter flags the change and the fix would require
  touching files outside the in-scope list.
- You are tempted to migrate `current_user()` too — don't; report that
  as a follow-up instead.

## Maintenance notes

- Root sphere and root site are deployment-constant; if this path ever
  shows up in profiling again, per-process caching of the root pair is
  the next lever (deliberately deferred — cache invalidation on sphere
  edits needs design).
- If `SitesService` grows further, consider whether
  `SpherePanelServiceProtocol.read`/`is_manager`
  (`pacts/multiverse.py:137-147`) and `SitesServiceProtocol` should
  merge; watch for duplication.
- Reviewers should scrutinize: the `is_manager` behavior is unchanged
  for anonymous users, and `SitesContextData` keys are untouched
  (templates depend on them).
