# Plan 002: Run pip-audit and deptry in CI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 0bec0f2..HEAD -- .github/workflows mise.toml`
> If those paths changed since this plan was written, compare the
> "Current state" excerpts against the live files before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `0bec0f2`, 2026-07-09

## Why this matters

`pip-audit` (CVE scanner) and `deptry` (unused/undeclared dependency
checker) are installed dev dependencies, but they only run inside the
manual `mise run update` task. No CI job executes them, so a
newly-disclosed CVE in Django, authlib, cryptography, requests, etc.
reaches production unnoticed until someone happens to run a manual
dependency-update chore. This is a public-facing site handling auth and
PII; advisory scanning must be automatic — on lockfile changes and on a
weekly schedule (CVEs appear without any commit happening).

## Current state

- `.github/workflows/ci.yml` — jobs `checks`, `varlock-scan`,
  `impeccable`, `frontend-analysis`, `test-postgres`, `test`; none runs
  `pip-audit` or `deptry`. The setup recipe every Python job uses
  (`ci.yml:22-26`):

  ```yaml
  steps:
    - uses: actions/checkout@v4
    - uses: jdx/mise-action@v2
    - run: mise install
    - run: mise exec -- poetry install
  ```

- `mise.toml` `[tasks.update]` — the only place the tools run today:

  ```toml
  [tasks.update]
  description = "Update all dependencies: mise tools, pip, Poetry packages"
  run = [
      "mise upgrade",
      "pip install -U pip",
      "poetry update",
      "deptry src tests",
      "pip-audit .",
      "poetry show -o",
  ]
  ```

- `pyproject.toml:63` declares `pip-audit`; `pyproject.toml:52`
  declares `deptry`; `[tool.deptry]` config exists at
  `pyproject.toml:128-143` with per-rule ignores — deptry is already
  tuned for this repo.
- CI triggers (`ci.yml:4-10`) are `pull_request` and `push` to
  master/main with `paths-ignore: ["docs/**"]`.
- Repo conventions for workflows: yaml starts with `---`, two-space
  indent, `permissions: contents: read` (see `ci.yml:1-17`). Workflows
  are linted by `actionlint` and `yamllint` via the pre-commit hooks.

## Commands you will need

| Purpose         | Command                          | Expected on success  |
|-----------------|----------------------------------|----------------------|
| Install         | `mise install && poetry install` | exit 0               |
| Run the audit   | `mise run audit`                 | exit 0 (see Step 1)  |
| CI-style checks | `mise run prcheck`               | exit 0               |

## Scope

**In scope** (the only files you should modify):

- `mise.toml` (add one task)
- `.github/workflows/audit.yml` (create)

**Out of scope** (do NOT touch, even though they look related):

- `.github/workflows/ci.yml` — keep the existing pipeline untouched; a
  separate workflow lets the audit run on a schedule without re-running
  the whole test matrix.
- `[tasks.update]` in `mise.toml` — leave the manual chore as is.
- `pyproject.toml` — do not add blanket deptry/pip-audit ignores (see
  STOP conditions).

## Git workflow

- Branch off the default branch; commit style example:
  `ci: audit dependencies with pip-audit and deptry`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a mise `audit` task

In `mise.toml`, under the `## Dependencies` section next to
`[tasks.update]`, add:

```toml
[tasks.audit]
description = "Audit dependencies: known CVEs (pip-audit), drift (deptry)"
run = ["pip-audit .", "deptry src tests"]
```

Note the invocations mirror `[tasks.update]` exactly — they are the
repo's proven forms.

**Verify**: `mise run audit` → exit 0. If `pip-audit .` fails with a
usage error (not an advisory), retry the task with plain `pip-audit`
and keep whichever form works, matching it in the task. If either tool
reports real findings, see STOP conditions.

### Step 2: Create the audit workflow

Create `.github/workflows/audit.yml`:

```yaml
---
name: Dependency audit

on:
  pull_request:
    paths:
      - poetry.lock
      - pyproject.toml
      - .github/workflows/audit.yml
  push:
    branches: ["master", "main"]
    paths:
      - poetry.lock
      - pyproject.toml
  schedule:
    - cron: "17 6 * * 1"
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: jdx/mise-action@v2
      - run: mise install
      - run: mise exec -- poetry install
      - run: mise run audit
```

The paths filter keeps it off unrelated PRs; the Monday cron catches
advisories published between lockfile changes; `workflow_dispatch`
allows manual runs.

**Verify**: `actionlint .github/workflows/audit.yml` → no output,
exit 0.

### Step 3: Full gate

**Verify**: `mise run prcheck` → exit 0. Committing must pass the
pre-commit hooks (yamllint, actionlint run automatically).

## Test plan

- No Python tests — this is CI wiring. The verification gates are:
  `mise run audit` green locally, `actionlint` green, and the hooks
  passing on commit.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `mise run audit` exits 0
- [ ] `actionlint .github/workflows/audit.yml` exits 0
- [ ] `grep -c "pip-audit" mise.toml` returns 2 (update task + audit
  task)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `pip-audit` reports one or more advisories against the current
  lockfile: report the advisory IDs and affected packages. Do NOT
  silence them with `--ignore-vuln` and do NOT bump dependencies
  yourself — version changes need human review.
- `deptry src tests` reports violations: report them verbatim. Do NOT
  add ignores to `[tool.deptry.per_rule_ignores]` on your own.
- Both invocation forms of pip-audit fail for tool reasons (network,
  index access) after a retry.

## Maintenance notes

- Scheduled-run failures only notify via GitHub's default workflow
  e-mail; if the team wants louder alerts, wire a notification step
  later (deliberately out of scope here).
- When an advisory has no fixed release yet, the human decision is
  between `--ignore-vuln PYSEC-...` with an expiry comment or accepting
  a red audit; record whichever in `mise.toml` next to the task.
- Reviewers should scrutinize: the paths filter list — if dependency
  manifests move (e.g. a second lockfile appears), extend it.
