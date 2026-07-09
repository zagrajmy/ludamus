# Plan 005: Fix onboarding and refactor-index doc drift

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 0bec0f2..HEAD -- README.md docs/refactors/README.md PLAN_PROPOSAL_PANEL_CRUD.md`
> If those files changed since this plan was written, compare the
> "Current state" excerpts against the live files before proceeding; on
> a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `0bec0f2`, 2026-07-09

## Why this matters

Three verified drift points mislead exactly the audiences the docs
exist for. (1) The README quick-start tells newcomers to run
`mise bootstrap`, which invokes mise's built-in bootstrap feature (brew
packages only) instead of the repo's `bootstrap` *task* — so a
copy-pasting newcomer gets no `.env.local`, no migrations, no demo
data, and a confusing first run. (2) The refactor index — whose stated
purpose is "so any session can pick up where the last one left off" —
points the next contributor at migrating Auth/Profile views, work that
already landed in PRs #534 and #540; the accurate next slice lives only
in the sub-doc. (3) A 53 KB implemented one-off plan file sits in the
repo root; the repo's own TODO kanban lists cleaning up such files.

## Current state

- `README.md:16-20` — the quick-start block:

  ```bash
  mise install            # Python, Node, Poetry, ast-grep
  mise bootstrap      # .env, deps, migrations, demo data — idempotent
  mise dev                # Django :8000 + Vite :5173
  ```

  The real task is `[bootstrap]` in `tasks.toml:71` (env file,
  `poetry install`, migrations, cache table, vendor download, demo
  data), invoked as `mise run bootstrap`. `README.md:26` and
  `docs/LOCAL_DEV.md:6` already use the correct `mise run bootstrap`
  form; `mise.toml:31-33` defines the colliding built-in
  `[bootstrap.packages]` feature.

- `docs/refactors/README.md`, "Status at a glance" table: row 1's
  "Next step (short)" cell currently reads:

  ```text
  Migrate Auth/Profile views out of `adapters/web/django/views.py`
  ```

  Stale: `git log` shows `refactor(gates): migrate Auth views into
  gates/crowd` (#534) and `refactor(gates): migrate
  Profile/connected-users/claim views into gates/crowd (#540)` already
  merged. The per-refactor file is current —
  `docs/refactors/glimpse-strangler.md:86-90` says:

  ```markdown
  ## Next step

  Migrate the remaining **Public Event Pages** and **Enrollment** views
  ```

  naming `SessionEnrollPageView`, `SessionEnrollmentAnonymousPageView`,
  `ProposalAcceptPageView`. Rows 2-7 of the table were checked and are
  NOT stale — leave them untouched.

- `PLAN_PROPOSAL_PANEL_CRUD.md` — 53 KB plan at the repo root,
  committed 2026-07-05; the panel proposal CRUD it describes shipped
  (TODO.md marks "Proposals management" items ✅; the
  `refactor-proposal-v2` branch merged in `8bb3955`). `TODO.md:122-124`
  lists: "Clean up internal files - gitignore or remove task/plan
  files". Git history preserves the content after deletion.

- Conventions: markdown is linted by `markdownlint-cli2` (80-char
  lines; tables exempt) via pre-commit hooks; docs changes don't
  trigger the CI test matrix (`ci.yml` has `paths-ignore: ["docs/**"]`)
  but README/root files do.

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Lint markdown | `markdownlint-cli2 README.md docs/refactors/README.md` | exit 0 |
| Full CI checks | `mise run prcheck` | exit 0 |

## Scope

**In scope** (the only files you should modify):

- `README.md` (one line)
- `docs/refactors/README.md` (one table cell)
- `PLAN_PROPOSAL_PANEL_CRUD.md` (delete)

**Out of scope** (do NOT touch, even though they look related):

- `docs/refactors/glimpse-strangler.md` — already correct.
- Rows 2-7 of the refactor status table — verified not stale.
- `TODO.md` — its cleanup item covers more files than this one; leave
  the kanban to the maintainers.
- `RELEASE_NOTES.md` — known to lag, but refreshing it is editorial
  work for a human, not mechanical drift-fixing.
- `.gitignore` — deleting the one stale file doesn't justify a new
  ignore pattern.

## Git workflow

- Branch off the default branch; commit style example:
  `docs: fix bootstrap command, sync refactor index, drop shipped plan`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Fix the README quick-start

In `README.md:18`, change `mise bootstrap` to `mise run bootstrap`,
keeping the comment and aligning the column spacing with the
neighboring lines:

```bash
mise install            # Python, Node, Poetry, ast-grep
mise run bootstrap      # .env, deps, migrations, demo data — idempotent
mise dev                # Django :8000 + Vite :5173
```

**Verify**: `markdownlint-cli2 README.md` → exit 0.

### Step 2: Sync refactor-index row 1

In `docs/refactors/README.md`, replace row 1's "Next step (short)" cell
with the sub-doc's actual next step:

```text
Migrate Public Event Pages + Enrollment views out of `views.py`
```

Keep the rest of the row (link, status emoji) unchanged. Table rows are
exempt from the 80-char rule.

**Verify**: `markdownlint-cli2 docs/refactors/README.md` → exit 0, and
the table renders (row count unchanged:
`grep -c '^|' docs/refactors/README.md` returns the same number as
before the edit).

### Step 3: Remove the shipped plan file

```bash
git rm PLAN_PROPOSAL_PANEL_CRUD.md
```

**Verify**: `test ! -f PLAN_PROPOSAL_PANEL_CRUD.md` → exit 0.

### Step 4: Full gate

**Verify**: `mise run prcheck` → exit 0; committing passes the
pre-commit hooks (markdownlint, codespell).

## Test plan

- No code changes — the verification gates are markdownlint on the two
  edited files and a green `mise run prcheck`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "mise bootstrap " README.md` returns no matches;
  `grep -c "mise run bootstrap" README.md` returns 2
- [ ] `grep -c "Auth/Profile" docs/refactors/README.md` returns 0
- [ ] `PLAN_PROPOSAL_PANEL_CRUD.md` does not exist
- [ ] `mise run prcheck` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- Row 1 of the status table no longer says "Auth/Profile" (someone
  synced it already) — skip Step 2 and report.
- `PLAN_PROPOSAL_PANEL_CRUD.md` gained commits after `0bec0f2` — check
  with `git log --oneline 0bec0f2..HEAD -- <that file>`; it may be in
  active use again; do not delete, report.
- You are tempted to "refresh" other doc files (RELEASE_NOTES.md,
  LOCAL_DEV.md, other table rows) — don't; report suggestions instead.

## Maintenance notes

- The refactor index asks maintainers to keep the table in sync as
  work lands; row 1 will drift again when the Enrollment slice merges —
  whoever lands that migration should update both the sub-doc and this
  row.
- Deferred, surfaced by the same audit: a toolchain glossary
  (aube/aubr/varlock/hk are used throughout the task files but defined
  nowhere in `docs/`), and a decision on whether `RELEASE_NOTES.md` is
  a maintained changelog or a one-shot snapshot (TODO ticket 23 covers
  the changelog question).
