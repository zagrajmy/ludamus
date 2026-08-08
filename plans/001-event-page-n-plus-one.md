# Plan 001: Eliminate the two N+1 query patterns on the public event page

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 337cdde7..HEAD --
> src/ludamus/adapters/web/django/views.py tests/integration/web/chronology/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `337cdde7`, 2026-06-10
- **Tracking issue**: closes part of zagrajmy/ludamus#323 ("improve perf for big
  event pages")

## Why this matters

The public event page (`/event/<slug>/`) is the highest-traffic page in the app
and the flagship Kapitularz event has hundreds of sessions. The view issues
**two extra queries per session**: one because the participations loop bypasses
the prefetch cache, and one because session field values are never prefetched.
A 200-session event page issues 400+ avoidable queries. GitHub issue #323
tracks this slowness; issue #306 asks for N+1 detection in tests — this plan
fixes the worst offender and adds the first query-count regression test.

## Current state

- `src/ludamus/adapters/web/django/views.py` — legacy view module;
  `EventPageView` builds the public event page.

The sessions queryset (`views.py:809-833`) prefetches participations but NOT
`field_values`:

```python
event_sessions = (
    Session.objects.filter(agenda_item__space__area__venue__event=self.object)
    .select_related("presenter", "agenda_item__space", "sphere")
    .prefetch_related(
        "tags__category",
        "session_participations__user__manager",
        "session_participations__user__connected",
        "agenda_item__space__area__venue__event__enrollment_configs",
    )
    .annotate(...)  # enrolled_count_cached, waiting_count_cached
    .order_by("agenda_item__start_time")
)
```

**N+1 #1** — `views.py:1135` (inside the per-session loop in
`_get_session_data`): `session.field_values.all()` is not prefetched on
`event_sessions`, so each session issues a fresh query (and DTO building
touches `fv.field`, so prefetch must include `__field`):

```python
field_values=_field_value_dtos_from_models(session.field_values.all()),
```

**N+1 #2** — `views.py:1158-1160` (same loop): calling
`.select_related("user").all()` on the related manager builds a *new* queryset
and ignores the `session_participations__user__*` prefetch entirely — one query
per session:

```python
for sp in session.session_participations.select_related(
    "user"
).all()
```

Note: a prefetch for `field_values__field` already exists on the *Event*
queryset (`views.py:796`), but `_get_session_data` iterates the separate
`event_sessions` queryset, so it doesn't help.

Repo conventions: strict mypy + ruff `select=["ALL"]`; never add
noqa/type-ignore comments. View tests live in
`tests/integration/web/chronology/` and use the `assert_response` utility.

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise run bootstrap` | exit 0 (idempotent) |
| All tests | `mise run test` | all pass |
| One test file | `poetry run pytest tests/integration/web/chronology/test_event_page.py -x -q` | all pass |
| Lint+format (autofix) | `mise run check` | exit 0 |
| CI-style lint | `mise run prcheck` | exit 0 |

(If `test_event_page.py` is named differently, find it with
`grep -rln "EventPageView\|chronology:event" tests/integration/web/chronology/`.)

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/adapters/web/django/views.py` (the `EventPageView` queryset and
  `_get_session_data` loop only)
- the existing event-page integration test file in
  `tests/integration/web/chronology/` (add a query-count test)

**Out of scope** (do NOT touch, even though they look related):

- The `tags__category` prefetch on line 813 — Tag removal is owned by open PR #234.
- `Session.effective_participants_limit` / `is_enrollment_available` model
  properties — in-memory config iteration; separate, lower-value optimization.
- The enrollment POST flow (`SessionEnrollPageView`) — open PRs #359/#337 are
  rewriting it.
- Any repo/service-layer migration (`request.services`) — that's the
  strangler-fig program, not this fix.

## Git workflow

- Branch: `advisor/001-event-page-n-plus-one`
- Commit style: imperative, lowercase-ish, like `git log`: e.g. "Use
  scrollbar-gutter: stable to reserve scrollbar space". One commit for the fix,
  one for the test is fine.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the missing prefetch and fix the loop

In `views.py`, in `EventPageView.get_context_data`, extend the
`event_sessions` prefetch list with `"field_values__field"`:

```python
.prefetch_related(
    "tags__category",
    "session_participations__user__manager",
    "session_participations__user__connected",
    "field_values__field",
    "agenda_item__space__area__venue__event__enrollment_configs",
)
```

In `_get_session_data` (`views.py:1158-1160`), change the participations
iteration to use the prefetch cache:

```python
for sp in session.session_participations.all()
```

(`sp.user` is already cached by the `session_participations__user__manager`
prefetch chain.)

**Verify**: `poetry run pytest tests/integration/web/chronology/ -x -q` → all pass

### Step 2: Add a query-count regression test

In the existing event-page test file, add a test that renders the event page
with **two different session counts** and asserts the query count does not grow
with the number of sessions. Use `django_assert_num_queries` from
pytest-django (already installed), capturing the count once and comparing:

```python
def test_event_page_query_count_is_constant_in_session_count(
    client, event_with_sessions_factory, django_assert_num_queries
):
    # Arrange: event A with 2 sessions, event B with 8 sessions
    # (build with the existing factories used by neighboring tests)
    # Act + Assert: render both; captured query counts must be equal
```

Model the arrangement on the neighboring tests in the same file (factories
from `tests/integration/conftest.py`: `EventFactory`, `SessionFactory`,
`AgendaItemFactory`, etc. — follow whatever the existing event-page tests use
to create scheduled sessions). Sessions must have field values and
participations so the fixed paths are exercised: attach at least one
`SessionFieldValue` and one confirmed `SessionParticipation` per session.

The cleanest assertion pattern when the absolute count is noisy:

```python
from django.test.utils import CaptureQueriesContext
from django.db import connection

with CaptureQueriesContext(connection) as ctx_small:
    client.get(url_small_event)
with CaptureQueriesContext(connection) as ctx_big:
    client.get(url_big_event)
assert len(ctx_big) == len(ctx_small)
```

**Verify**: `poetry run pytest <test file> -x -q` → all pass. Temporarily
revert the Step 1 prefetch change and confirm the new test FAILS (proves it
guards the regression), then restore.

### Step 3: Full gate

**Verify**: `mise run test` → all pass; `mise run prcheck` → exit 0.

## Test plan

- New: `test_event_page_query_count_is_constant_in_session_count` (Step 2) —
  this is the regression guard for both N+1s.
- Existing event-page tests must stay green — they cover rendering
  correctness (participant avatars, field-value rows).

## Done criteria

- [ ] `grep -n 'session_participations.select_related'
  src/ludamus/adapters/web/django/views.py` inside `_get_session_data` returns
  no matches
- [ ] `grep -n '"field_values__field"' src/ludamus/adapters/web/django/views.py`
  matches inside the `event_sessions` prefetch
- [ ] New query-count test exists and passes; fails when Step 1 is reverted
- [ ] `mise run test` exits 0
- [ ] `mise run prcheck` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts above don't match the live code (the file is actively edited by
  open PRs; lines may have shifted — small offsets are fine, different code is not).
- The query-count test cannot be made deterministic (e.g. sphere/site caching
  varies between requests) after one focused attempt — report what varies.
- Fixing the loop changes rendered output (participant ordering on the page) —
  the old code had no explicit ordering either, but if a test asserts ordering,
  report rather than re-sorting in Python.

## Maintenance notes

- Anything added to `SessionData` that touches a new relation must be added to
  the `event_sessions` prefetch; the new query-count test will catch misses.
- Follow-up (deferred): per-session in-memory iteration of
  `get_active_enrollment_configs()` / `get_most_liberal_config()`
  (`models.py` Session properties) is O(sessions × configs) — only worth it if
  the page is still slow after this lands.
- Follow-up (deferred): issue #306 (automatic N+1 detection) — this test is the
  manual version; a `pytest-django` query-budget fixture could generalize it.
