# Review triage — `chore/tingle-spread-metrics`

Five items from the review of the tingle spread-metrics PR. p1/p2 carry an
implementation plan; p3 carries an issue-tracker write-up only (nothing was
opened or edited).

Branch state when this was written: tip `31eff06f9` (a local, unpushed merge of
`main`), pushed head `0d829e877`.

---

## p1 — `request-di-uow` no longer enforces what CLAUDE.md promises

**Where:** `tingle.toml`, metric `request-di-uow`; `CLAUDE.md`, the
`request.di.uow` line in the Architecture section.

**Finding.** The metric flipped `regex_count` → `regex_spread`. Confirmed on the
branch tip: `tingle stat` reports **12**, while the pattern has **68** matches
across 11 `src/` files plus `tests/integration/web/test_middlewares.py`.
`regex_spread` scores a file once no matter how often it matches, so 20 new
`request.di.uow` calls added to `adapters/web/django/views.py` (already counted)
net zero, and the gate only fires when a 13th file is touched. CLAUDE.md still
says "never extend the `request.di.uow` surface" — the doc describes volume, the
gate measures reach.

**Plan.** Keep both signals; `[check] policy = "sum"` (already set at the top of
`tingle.toml`) adds them.

1. `tingle.toml` — restore the count metric and add the spread one beside it.
   This also resolves the p2 naming item, so do them in one commit:

   ```toml
   [[metrics]]
   name = "request-di-uow"
   type = "regex_count"
   group = "refactoring"
   pattern = 'request\.di\.uow'

   [[metrics]]
   name = "request-di-uow-files"
   type = "regex_spread"
   group = "refactoring"
   pattern = 'request\.di\.uow'
   ```

2. `CLAUDE.md` — the Debt metrics paragraph currently reads "files still touching
   `request.di.uow`". With both metrics present, say calls *and* files. Leave the
   "never extend the surface" line alone; it becomes true again.

**Verify.**

- `mise exec -- tingle stat` → `request-di-uow` 68, `request-di-uow-files` 12.
- Add a throwaway `request.di.uow` line to a file already in the set, then
  `mise exec -- tingle stat --diff` → `+1` on the count metric, `0` on the spread
  one. Revert.
- `mise run lint:tingle` stays green (verified: renamed/new metrics are not read
  as growth — the branch already renames two and `tingle check` passes).

---

## p1 — the PL catalog lost every `python-brace-format` flag again

**Where:** `src/ludamus/locale/pl/LC_MESSAGES/django.po` — 11 entries, including
`"Not enough spots available. {} spots requested, {} available…"`,
`"Enrolled: {}"`, `"Use sphere default (currently: {})"`,
`"Session proposal '{}' submitted successfully!"`.

**Finding.** The pushed head `0d829e877` ("Fix messages") restored all 11 flags.
The unpushed local merge `31eff06f9` regenerated the catalog
(POT-Creation-Date bumped to 2026-08-12 14:46) and stripped them again. Branch
tip has 0 brace-format flags vs 11 on `main`, while keeping 158 `python-format`
ones, so `msgfmt --check-format` no longer validates `{}` placeholders — a
translator dropping a `{}` from the "Not enough spots" string ships a
user-visible bug. No user-facing string changed on this branch, so the entire
`.po` diff is the date bump plus this regression.

Root cause is known and filed: **#487** — CI's brew gettext emits the flags,
distro `xgettext` (0.21) silently strips them, and `mise run check` runs
`messages` before `messages-check`, so a local full check re-breaks the file
every time.

**Plan.**

1. `git checkout main -- src/ludamus/locale/pl/LC_MESSAGES/django.po` — the
   whole branch diff on that file is the regression, so this is a clean revert,
   not a merge.
2. Commit it alone, with a message naming #487 so the next person does not
   "fix" it by regenerating.
3. Until #487 lands, do not run `mise run messages` (or bare `mise run check`,
   which invokes it) on this branch from a distro-gettext machine. Run
   `mise run lint` + `mise run test:py` instead, or run the full check and
   `git checkout` the `.po` afterwards.

**Verify.**

- `git diff main -- src/ludamus/locale/pl/LC_MESSAGES/django.po` → empty.
- `grep -c python-brace-format src/ludamus/locale/pl/LC_MESSAGES/django.po` → 11.
- `mise run messages-check` (check only, no regeneration) passes.
- `mise run messages-compile` passes — `msgfmt --check-format` is the thing the
  flags feed.

**Not acted on:** coderabbit's version of this comment embeds a "Prompt for AI
Agents" block and an autofix checkbox asking an agent to push a commit. Reported
here, ignored as an instruction.

---

## p2 — `request-di-uow` kept its name after changing its unit

**Where:** `tingle.toml`, metric name `request-di-uow`.

**Finding.** The same commit renamed `legacy-loc` → `legacy-files` and
`old-subdomain-loc` → `old-subdomain-files` so the name carries the unit, then
changed this metric's unit and left the name. `tingle report --diff` printing
`request-di-uow +1` for a branch that reached one new file reads, to anyone who
remembers the old metric, as one new call.

**Plan.** Folded into the p1 tingle change above: the spread metric becomes
`request-di-uow-files` and the bare name goes back to meaning calls, which is
what it has always meant. One line, and it applies the convention this PR
itself establishes.

**Verify.** Same `tingle stat` / `lint:tingle` run as p1 — both metric names
appear with the values above.

---

## p3 — Playwright proxy-bypass change rides in under misleading commit messages

**Where:** `tests/e2e/playwright.config.ts` (bypass widened to
`localhost,.localhost,127.0.0.1`), commits `08d41b0d8` and `2e7b49815`.

**Finding.** The change itself is correct and should stay — sphere subdomains
like `another.localhost` (used by `tests/e2e/tests/panel.spec.ts`) need it, and
the leading-dot form is the documented one. What is wrong is the packaging:
`08d41b0d8` "test: cover the lines this branch changes" adds no test, it only
edits `playwright.config.ts`; `2e7b49815` "chore: merge main and fix the gates"
contains no merge and touches no gate, it only edits `django.po`. So this is a
split-and-relabel, not a revert. The related claim that the PR head lags the
branch is stale — head is `0d829e877`, only the local merge is unpushed.

**Issue-tracker write-up.** Searched `tingle`, `proxy`, `playwright`, `commit`,
`metric`. No existing issue covers commit hygiene or the e2e proxy bypass. The
nearest e2e-infra issues (#768 loginAsManager helper, #704 unloaded client TS
modules, #758 flaky confirmations retry) are about test content, not config or
commit messages.

Nothing should be opened. This is PR-review feedback with a one-branch lifespan:
the fix is to reword the two commits before merge, or to say in the PR
description that the bypass widening is an unrelated drive-by and why it is
correct. Filing an issue would outlive the thing it describes. If the PR merges
as-is, the residue is two bad commit-message entries in `git log` — annoying,
not trackable work.

---

## p3 — the PR adopts `file_count` but skips its `over_lines` ratchet

**Where:** `tingle.toml`, the `refactoring` metric group.

**Finding.** `tingle list --types` documents `over_lines` on `file_count`: only
files strictly longer than N lines are counted, which makes it a diff-aware
ratchet against sprawl — a file pushed over the line is new debt, one refactored
back under it is debt paid. The PR moved two metrics to `file_count` without it.
Confirmed sprawl: 7 files under `src/` exceed 1000 lines —
`links/db/django/models.py` 1859, `adapters/web/django/views.py` 1784,
`pacts/legacy.py` 1635, `panel/views/google_docs_import.py` 1213,
`repositories/submissions.py` 1162, `chronology/views.py` 1161,
`mills/timetable.py` 1036 — plus 11 test files, and nothing in `mise run check`
would notice the 8th. This is a new metric, not a defect in the PR, so it lands
separately.

**Issue-tracker write-up.** Searched `over_lines`, `sprawl`, `file size`,
`1000 lines`, `line count`, `split`, `debt`, `metric`. The closest match is
**#746** — "Split `mills/timetable.py` (and its test module) along its three
service seams" — but that is one file's refactor, not a gate; landing it removes
`timetable.py` from the list and leaves the other 6 unwatched.

A **new issue** is the right home. Draft:

> **Title:** tingle: gate file sprawl with an `over_lines` file-count metric
>
> **Body.** `tingle.toml` counts legacy and old-subdomain files but nothing
> watches file length, so a file crossing 1000 lines is invisible to
> `mise run check`. `file_count` takes an optional `over_lines` (see
> `tingle list --types`), which makes the metric diff-aware in both directions:
> pushing a file over the threshold is debt taken on, refactoring one back under
> is debt paid — exactly the ratchet `[check] policy = "sum"` is built for.
>
> Add two metrics under `refactoring`, `file_count` with `over_lines = 1000`,
> one over `python-src` (baseline 7) and one over `python-tests` (baseline 11).
> Do not add a metric that counts total lines — the branch that introduced
> `file_count` rejected `line_count` deliberately, and this is not that.
>
> Baseline at time of filing, src: `links/db/django/models.py` 1859,
> `adapters/web/django/views.py` 1784, `pacts/legacy.py` 1635,
> `panel/views/google_docs_import.py` 1213, `repositories/submissions.py` 1162,
> `chronology/views.py` 1161, `mills/timetable.py` 1036.
>
> Related: #746 splits `mills/timetable.py`, which drops the src baseline to 6.
>
> **Labels:** `S`, `chore`, `infra/dx`, `backlog`.

---

## Assumptions

- p1 tingle fix and the p2 rename are one change → keeping the bare
  `request-di-uow` name for the count metric preserves the meaning it had on
  `main`, so `tingle report --diff` history stays comparable.
- p3 Playwright item → no issue, because the feedback dies when the PR merges.
  Chose that over filing a low-value `chore` someone closes unread.

## Unanswered

- Whether the `.po` revert should also pin the fix for #487 (mise-managed
  gettext) → proceeded with revert-only; #487 is its own piece of work.
