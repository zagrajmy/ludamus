# Plan 004: Investigate why mills/pacts/inits/specs are absent from coverage reports

> **Executor instructions**: This is an INVESTIGATE plan — the deliverable is a
> diagnosis written into this file (section "Findings", bottom) plus, if the
> cause is a one-line config fix, that fix. If the fix is larger, report the
> diagnosis and proposed fix instead of implementing it. Honor STOP conditions.
> When done, update this plan's row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 337cdde7..HEAD -- pyproject.toml mise.toml`
> Mismatch with "Current state" = STOP.

## Status

- **Priority**: P2
- **Effort**: S (investigation; fix may grow)
- **Risk**: LOW (measurement only — but it gates merges)
- **Depends on**: none
- **Category**: tests / dx
- **Planned at**: commit `337cdde7`, 2026-06-10

## Why this matters

The repo enforces coverage hard: `coverage report --fail-under=93`
(`mise.toml:225`) and a codecov patch target of 96% (`codecov.yml`). But the
committed `coverage.xml` at the repo root contains **zero packages under
`ludamus.mills`, `ludamus.pacts`, `ludamus.inits`, or `ludamus.specs`** —
verified with `grep -c 'mills' coverage.xml` → 0 — even though unit tests for
mills exist (`tests/unit/test_mills.py`) and `[tool.coverage.run]` sets
`source = ["src"]` with no relevant omit. If the live coverage run has the
same blind spot, the 93%/96% gates are not protecting the business-logic layer
at all (services own enrollment, proposals, timetable logic). If `coverage.xml`
is just a stale artifact from a partial run, it should be gitignored so it
stops misleading people and tools.

## Current state

- `pyproject.toml` `[tool.coverage.run]`:

  ```toml
  branch = true
  source = ["src"]
  omit = [
      "src/ludamus/edges/*",
      "src/ludamus/adapters/db/django/migrations/*",
      "src/ludamus/client/*",
      "tests/template_checks.py",
  ]
  sigterm = true
  plugins = ["django_coverage_plugin"]
  core = "ctrace"
  ```

  Note the non-default `core = "ctrace"` (coverage's C tracer selection) on
  Python 3.14, plus the Django template plugin — either is a plausible culprit
  for silently missing modules.

- `mise.toml` test tasks: `[tasks.test]` runs
  `mise run _pytest -- tests tests/integration tests/unit` with
  `env.COVERAGE_FILE = "{{ config_root }}/.coverage.unit"`; line 225 runs
  `coverage report --fail-under=93`; there are separate e2e coverage files
  (`.coverage.e2e`) and presumably a combine step — read the `[tasks.cov*]`
  /coverage-related tasks in `mise.toml` to map the full pipeline first.

- Root artifacts: `coverage.xml` (627 KB), `.coverage` (1.7 MB),
  `.coverage.e2e` (488 KB) are present in the working tree. Check whether they
  are git-tracked: `git ls-files | grep -E 'coverage'`.

- `coverage.xml` packages present: `ludamus.adapters.web.*`, `ludamus.gates.*`,
  `ludamus.links.*`, `ludamus.templates.*` — i.e. everything EXCEPT the pure-
  Python layers (mills/pacts/inits/specs).

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Full test+coverage pipeline | `mise run test` | exit 0 |
| Fresh terminal report | `poetry run coverage report --include="*/mills/*"` (after a run) | the diagnostic datum |
| Targeted run | `poetry run pytest tests/unit --cov=ludamus --cov-report=term-missing 2>&1 \| grep mills` | mills lines appear or not |

## Scope

**In scope**:
- Reading `mise.toml`, `pyproject.toml`, CI workflow coverage steps
- Running the test suite locally (read-only side effects: coverage data files, which are already untracked clutter)
- A config-level fix in `pyproject.toml`/`mise.toml` if the cause is one line (e.g. `core` setting, missing combine, wrong `--cov` target)
- Adding `coverage.xml` / `.coverage*` to `.gitignore` if they turn out to be untracked clutter that's misleading (only if not already ignored)

**Out of scope**:
- Writing new tests for mills (follow-up once measurement is trusted)
- Changing the 93%/96% thresholds
- Touching codecov.yml

## Git workflow

- Branch: `advisor/004-coverage-mills-blindspot`
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Map the coverage pipeline

Read every coverage-related task in `mise.toml` (search `coverage`, `cov`,
`combine`, `xml`). Write down: which task produces `coverage.xml`, whether
`.coverage.unit` and `.coverage.e2e` are combined before reporting, and what
CI (`.github/workflows/ci.yml`) uploads to codecov.

**Verify**: you can name the exact command that produced the root `coverage.xml`.

### Step 2: Reproduce

Run `mise run test` (or the narrower unit task) and then:

```
poetry run coverage report --include="*/mills/*"
```

Two outcomes:
- **Mills covered in a fresh run** → the root `coverage.xml` is a stale/partial
  artifact (likely from the e2e run, which exercises only web layers... though
  mills should still execute — note what you find). Fix = ensure stale
  artifacts aren't committed/uploaded; add to `.gitignore` if untracked.
- **Mills missing in a fresh run too** → real measurement bug. Proceed to Step 3.

### Step 3 (only if missing in fresh runs): Bisect the config

Try in order, re-running the targeted command after each, reverting between tries:
1. Remove `core = "ctrace"` (fall back to default tracer) — known-newer knob, most suspicious on CPython 3.14.
2. Remove `plugins = ["django_coverage_plugin"]` temporarily.
3. Run pytest with explicit `--cov=ludamus.mills` to see whether pytest-cov's source resolution differs from `source = ["src"]`.

Identify the single change that makes mills appear.

**Verify**: `poetry run coverage report --include="*/mills/*"` shows
`tests/unit/test_mills.py`-driven coverage (mills/legacy.py, mills/chronology.py at >0%).

### Step 4: Fix or report

- One-line cause (e.g. drop/replace `core = "ctrace"`): apply it, confirm
  `mise run test` still exits 0 and the overall `--fail-under=93` still passes
  (it may DROP below 93 once previously-invisible files enter the denominator —
  if so, STOP and report the real number instead of lowering the threshold).
- Anything bigger (plugin incompatibility needing an upstream bump, pipeline
  restructure): write the diagnosis under "Findings" below and stop.

## Done criteria

- [ ] "Findings" section below filled in with: cause, evidence, fix applied or proposed
- [ ] If fixed: fresh `coverage report --include="*/mills/*"` non-empty AND `mise run test` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

- Including mills/pacts/inits/specs drops total coverage below the 93 gate —
  report the true number; threshold decisions belong to the maintainer.
- The cause is in `django_coverage_plugin` or coverage-core internals requiring
  a dependency change — report, don't bump deps unilaterally.

## Maintenance notes

- Whatever the cause, the lesson for CI: a coverage gate that silently loses
  whole packages still passes. Consider a canary assertion in the coverage
  task (e.g. `coverage report --include="*/mills/*" | grep -q legacy.py`).

## Findings

_(filled by executor)_
