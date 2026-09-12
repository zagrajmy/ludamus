# Plan 006: Regression guardrails — N+1 detection + factory-slug lint (#306)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command before moving on. On any STOP condition, stop and
> report. When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 337cdde7..HEAD --
> tests/integration/conftest.py tests/integration/utils.py rules/ sgconfig.yml`
> Mismatch with "Current state" = STOP.

## Status

- **Priority**: P1 (prevention — locks in plans 001/003 so the bug classes can't
  return)
- **Effort**: M
- **Risk**: MED (a new blanket assertion can flag many existing tests; the plan
  uses report-then-ratchet to control that)
- **Depends on**: plans/001 (its fix removes the loudest offenders), plans/003
  (stable suite before adding a new failure mode)
- **Category**: tests / dx
- **Planned at**: commit `337cdde7`, 2026-06-10
- **Tracking issue**: closes zagrajmy/ludamus#306 ("Detect N+1 queries in dev
  and tests")

## Why this matters

The audit found textbook N+1s on the highest-traffic page (fixed in plan 001),
and issue #306 asks for systematic detection. One-off query-count tests only
guard pages someone thought about. This repo has a better hook: every view
integration test makes requests through the pytest-django `client` fixture, so
a query-auditing test client gives N+1 detection on **every existing and
future view test for free**. Second guardrail: the flaky-factory bug class
(plan 003) gets an ast-grep rule so `Faker("slug")` can't be reintroduced —
the repo already runs ast-grep in `mise run check`/`prcheck` with custom rules
in `rules/`.

Dev-time visibility (the other half of #306) already exists:
django-debug-toolbar is installed for dev and shows duplicate queries. This
plan adds the *enforcement* half. If after Step 2 the data shows test-side
enforcement is impractical (too many legitimate repeats), the fallback
deliverable is report-only warnings + the lint rule — still a win; report it.

## Current state

- `tests/integration/conftest.py` — factory definitions and shared fixtures
  for the integration suite (pytest-django provides the `client` fixture; this
  conftest currently does not override it).
- `tests/integration/utils.py` — `assert_response(response, status_code, *,
  messages, contains, ...)` helper used by all view tests (lines 21-46). It
  runs *after* the request, so it cannot capture queries — that's why the
  client, not this helper, is the hook.
- `rules/` + `sgconfig.yml` — ast-grep config: `ruleDirs: [rules]`, two
  existing rules (`no-inline-color-var.yml`, `no-inline-theme-var.yml`). Read
  one before writing the new rule and match its structure (id, message,
  severity fields).
- `mise.toml` — the `ast-grep` task is part of `check`/`prcheck`; pytest runs
  via `mise run test` (wraps `_pytest`), single files via `poetry run pytest`.
- Django's official per-query hook is `connection.execute_wrapper(...)`
  (context manager) — no new dependency needed. Do NOT add `nplusone`
  (unmaintained) or other third-party detectors without asking.
- Repo rules that bind this plan: strict mypy (tests are excluded from mypy —
  see `exclude` in `[tool.mypy]` — but ruff ALL applies), never add
  noqa/type-ignore, no `ANY` for simple values in tests.

## Commands you will need

| Purpose | Command | Expected |
| --- | --- | --- |
| Integration tests | `poetry run pytest tests/integration -q` | all pass |
| Full suite | `mise run test` | all pass |
| ast-grep alone | `mise run ast-grep` | exit 0 |
| Lint gate | `mise run prcheck` | exit 0 |

## Scope

**In scope**:

- `tests/integration/conftest.py` (or a new `tests/integration/query_audit.py`
  imported from it) — the auditing client + fixture override
- `pyproject.toml` `[tool.pytest.ini_options]` — register the new marker
- `rules/no-faker-slug.yml` (create)
- Per-test `@pytest.mark.allow_duplicate_queries(...)` annotations where Step 2
  data justifies them

**Out of scope**:

- Production/dev middleware (debug-toolbar already covers dev; revisit only if
  the maintainer asks)
- Fixing any N+1 this detector finds beyond annotating it (file findings in
  the completion report instead — fixes are separate work)
- `tests/unit` and `tests/e2e`
- Adding any new third-party dependency

## Git workflow

- Branch: `advisor/006-regression-guardrails`
- Commits: (1) auditing client in report mode, (2) threshold + annotations
  flip to enforce, (3) ast-grep rule.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a query-auditing test client (report-only)

In `tests/integration/conftest.py` (or a helper module it imports), subclass
the Django test client so every request records SQL via `execute_wrapper`,
then override the `client` fixture:

```python
from collections import Counter
from django.db import connection
from django.test import Client


class QueryAuditClient(Client):
    audit_threshold = 8  # identical SELECT shapes per request
    last_duplicates: dict[str, int] = {}

    def request(self, **request):
        counts: Counter[str] = Counter()

        def recorder(execute, sql, params, many, context):
            if sql.lstrip().upper().startswith("SELECT"):
                counts[sql] += 1
            return execute(sql, params, many, context)

        with connection.execute_wrapper(recorder):
            response = super().request(**request)
        self.last_duplicates = {
            sql: n for sql, n in counts.items() if n > self.audit_threshold
        }
        if self.last_duplicates:
            self._report_duplicates(request)
        return response
```

Notes for the implementer:

- Count only SELECTs: factory setup INSERTs and bulk writes legitimately repeat.
- Identical SQL text is the dedup key — Django parameterizes queries, so an
  N+1 loop produces byte-identical SQL with different params. No normalization
  needed beyond that.
- In this step `_report_duplicates` only emits a warning
  (`warnings.warn(...)` with test id, count, and the first 200 chars of the
  SQL) — nothing fails yet.
- Override the fixture so the whole suite uses it:

```python
@pytest.fixture
def client():
    return QueryAuditClient()
```

(Check first how existing tests obtain clients — `grep -rn "def client\|client("
tests/integration/conftest.py` and confirm tests use the standard
`client` fixture rather than instantiating `Client()` directly; if a
significant fraction instantiate directly, STOP and report.)

**Verify**: `poetry run pytest tests/integration -q` → all pass (warnings allowed).

### Step 2: Measure, set the threshold, annotate true positives

Run the suite with warnings visible and collect every report:

```bash
poetry run pytest tests/integration -q -W default 2>&1 \
  | grep -A2 "duplicate quer" | sort | uniq -c | sort -rn \
  > /tmp/query-audit.txt
```

Triage the offenders:

- **Genuine N+1 in a view** → keep the warning, list the view in the
  completion report as a follow-up finding (do NOT fix here).
- **Legitimate repeat** (e.g. a permission check that genuinely runs once per
  formset row) → either raise the global `audit_threshold` (if it's a one-off
  spike just above 8) or add a marker escape hatch for that test.

Add the marker plumbing: register `allow_duplicate_queries` in
`pyproject.toml` `[tool.pytest.ini_options]` (`markers = [...]`), and have the
fixture read it:

```python
@pytest.fixture
def client(request):
    c = QueryAuditClient()
    c.enforce = not request.node.get_closest_marker("allow_duplicate_queries")
    return c
```

**Verify**: `/tmp/query-audit.txt` exists and every offender is either
annotated, above-threshold-justified, or listed in the completion report.

### Step 3: Flip to enforcement

Change `_report_duplicates` to `raise AssertionError` (or `pytest.fail`) when
`self.enforce` is true, with a message that names the SQL shape, the count,
and the escape hatch:

```text
Duplicate query detected (xN): SELECT ... — likely an N+1.
Fix the prefetch, or mark the test @pytest.mark.allow_duplicate_queries
with a comment explaining why the repeat is legitimate.
```

**Verify**: `mise run test` → all pass. Then prove the guard works: temporarily
revert plan 001's prefetch fix (`git stash` style, locally) and confirm the
event-page test now FAILS with the duplicate-query message; restore.

### Step 4: ast-grep rule banning `Faker("slug")`

Read `rules/no-inline-color-var.yml` for the house style, then create
`rules/no-faker-slug.yml` matching `Faker("slug")` in Python test files, with
a message pointing at the fix pattern:

```yaml
id: no-faker-slug
language: python
severity: error
message: Faker("slug") collides on unique columns and causes flaky tests; use
  Sequence(lambda n: f"<model>-{n}") instead (add Sequence to factory
  imports).
rule:
  pattern: Faker("slug")
```

Adjust keys to whatever the existing rules actually use (e.g. `files:`/path
scoping if supported in this ast-grep version — scope to `tests/**` if the
existing rules show how; otherwise repo-wide is acceptable since production
code doesn't use factory_boy).

**Verify**: `mise run ast-grep` → exit 0 on clean tree. Then add a scratch
`slug = Faker("slug")` line to `tests/integration/conftest.py`, run
`mise run ast-grep` → exits non-zero flagging it; remove the scratch line.

### Step 5: Full gate

**Verify**: `mise run test` → all pass; `mise run prcheck` → exit 0.

## Test plan

- The detector itself is exercised by the whole suite; its negative case is
  Step 3's revert-and-fail proof and Step 4's scratch-line proof.
- Add one direct unit-style test for `QueryAuditClient` in
  `tests/integration/` (e.g. a view known to repeat a SELECT under a marker)
  ONLY if Step 2 surfaced a stable example; otherwise the revert-proof
  suffices — don't manufacture a synthetic view for it.

## Done criteria

- [ ] `client` fixture in `tests/integration/conftest.py` returns the auditing
  client; enforcement on by default
- [ ] `allow_duplicate_queries` marker registered in `pyproject.toml` and honored
- [ ] Reverting plan 001's prefetch locally makes the suite fail with the
  duplicate-query message (verified once, then restored)
- [ ] `rules/no-faker-slug.yml` exists; scratch violation is caught by
  `mise run ast-grep`
- [ ] `mise run test` exits 0; `mise run prcheck` exits 0
- [ ] Completion report lists every view the detector flagged as a real N+1
  (these are new findings, not fixed here)
- [ ] `plans/README.md` status row updated

## STOP conditions

- More than ~15 tests need `allow_duplicate_queries` annotations — the
  threshold is wrong or the suite has systemic N+1s; report the distribution
  from Step 2 instead of annotating en masse.
- Tests bypass the `client` fixture (instantiate `Client()` directly) in more
  than a handful of places — the hook point assumption fails; report.
- `execute_wrapper` interacts badly with the postgres test job
  (`mise run test:postgres`, CI `test-postgres`) — e.g. connection pooling
  differences; report rather than special-casing per backend.
- The ast-grep version in use doesn't support the rule shape and the existing
  rules don't show an alternative — report the version and proposed syntax.

## Maintenance notes

- The threshold (8) is a tripwire, not a budget — teams should lower it over
  time, not raise it. Raising it requires the same scrutiny as deleting a test.
- When the strangler-fig migration moves a view to `request.services`, its
  repo methods own the prefetches; this detector is what catches a migration
  that forgets them.
- Deferred: dev-server duplicate-query logging (debug-toolbar covers it);
  unit-test coverage of mills query patterns (mills don't touch the DB by
  design — links do, and links are exercised through these view tests).
- Related future ratchet: a coverage canary asserting mills appear in coverage
  reports — belongs to plan 004's fix, noted there.
