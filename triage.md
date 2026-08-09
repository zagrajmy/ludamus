# Review triage — `chore/tingle-spread-metrics`

State at triage: PR head `5cd4fbf`; three unpushed commits on top
(`43134bd5` merge main, `2e79481` django.po, `08d41b0d` playwright config).

## P1 — before pushing

### 1. Drop the django.po regeneration (`2e79481`)

Verified: `main` has 11 `python-brace-format` flags, this branch has 0; the 152
`python-format` entries survive. This is the known gettext version skew, already
filed as **#487** ("messages-check churn: local gettext strips the
python-brace-format flags CI's gettext emits") — the flags come back on the next
CI-side regeneration, so committing the stripped catalog just flips the
ping-pong. No string on this branch changed, so the commit has no reason to
exist here.

Changes:

- Drop the commit. It is unpushed, so no force push is involved:
  `git rebase --onto 43134bd5 2e79481 HEAD` (replays only `08d41b0d`).
- If the rebase is unwanted, `git revert 2e79481` is equivalent for review
  purposes.

Verify:

- `git diff main -- src/ludamus/locale/pl/LC_MESSAGES/django.po` → empty.
- `grep -c python-brace-format src/ludamus/locale/pl/LC_MESSAGES/django.po` → 11.
- Do **not** run `mise run messages` to "fix" it locally — that is the bug in
  #487; leave the catalog untouched.

### 2. Split the branch: metrics / proxy bypass / nothing else

Verified: `2e79481` "chore: merge main and fix the gates" contains no merge and
touches no gate — only the `.po`. `08d41b0d` "test: cover the lines this branch
changes" adds no test — it widens the Playwright proxy bypass to
`localhost,.localhost,127.0.0.1` so sphere subdomains (`another.localhost`)
skip the egress proxy. The proxy fix is correct; it is e2e infrastructure, not
metrics, and its message describes work it does not do.

Changes:

- After P1.1, cherry-pick `08d41b0d` onto a fresh branch off `main`
  (`fix/e2e-proxy-bypass-sphere-subdomains`), reword the message to what it
  does, and open it as its own PR.
- Reset this branch to `43134bd5` so it carries only `tingle.toml` + docs, then
  push (`git push` — no force needed once the drop happened pre-push).
- Nothing else lands here: no catalog, no e2e config.

Verify:

- `git log --oneline main..HEAD` on this branch → `5cd4fbf`, `43134bd5` only.
- `git diff main..HEAD --stat` → `tingle.toml`, `docs/**`, `CLAUDE.md` only.
- On the proxy branch: `mise run test:e2e` (or a single sphere-subdomain spec)
  passes with the egress proxy set.

## P2 — same day, on the metrics branch

### 3. `request-di-uow`: keep volume, add spread

`regex_spread` scores a file once. The pattern hits 67 times across 11 files
today, so twenty new `request.di.uow` calls inside
`src/ludamus/adapters/web/django/views.py` net zero — the gate only fires on a
new 12th file. CLAUDE.md says "never extend the `request.di.uow` surface", and
extending inside an already-dirty file is the daily case.

Changes — `tingle.toml`, the `refactoring` group:

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

Verify:

- `tingle stat` → `request-di-uow` = 67, `request-di-uow-files` = 11.
- Scratch commit adding one `request.di.uow` line to an existing legacy view →
  `tingle stat --diff` shows +1 on the count, 0 on the spread; `tingle check`
  fails. Discard the scratch commit.
- `mise run lint:tingle` green on the real branch.

### 4. CLAUDE.md "Debt metrics (tingle)" — describe what is actually measured

The rename reached `docs/agents/architecture.md` and
`docs/refactors/pacts-mills-split.md` but not the file every contributor and
agent loads at session start. It still advertises "legacy LOC", which after
this PR nothing counts.

Changes — CLAUDE.md, the sentence listing what `tingle.toml` counts: replace
"suppression comments, `Any`, `request.di.uow`, legacy LOC, …" with the
post-PR truth, naming both the per-call and per-file view of
`request.di.uow` and legacy/old-subdomain **files** (plus LOC if item 5/6
land). Do this in the same commit as the metric edits so the doc and the gate
never disagree.

Verify: `mise run lint:hk` (markdownlint) green; re-read the paragraph against
`tingle list` output — every metric family named in prose exists.

### 5. `legacy-files`: keep a LOC metric alongside the file count

`file_count_diff` counts created minus deleted files. `adapters/web/django/
views.py` (1,773 lines, inside `ranges.legacy-code`) can grow to 3,000 without
moving the metric — and bolting onto an existing legacy module is the likeliest
regression in that range.

Changes — `tingle.toml`:

```toml
[[metrics]]
name = "legacy-loc"
type = "line_count"
group = "refactoring"
ranges = ["legacy-code"]
```

kept next to the existing `legacy-files`.

Tension to state in the PR body, not design around: this is the metric the PR
deleted for scale reasons (~4,900 against counters in the tens, so under
`policy = "sum"` deleting one legacy module buys hundreds of noqa comments).
Re-adding it restores that offset budget. Add it anyway — growth-in-place is
the failure the file count cannot see — and say in the PR that if the offset
proves abusable the fix is a per-group policy in tingle, not dropping the
signal.

Verify:

- `tingle stat` → `legacy-loc` matches
  `wc -l` over `src/ludamus/adapters/**/*.py` plus `src/**/legacy.py`.
- Scratch commit appending 50 lines to `adapters/web/django/views.py` →
  `tingle stat --diff` +50, `tingle check` fails. Discard.

### 6. `old-subdomain-files`: add a LOC metric on the same range

`ranges.old-subdomain-modules` is five package trees, and a rename is one
`git mv`, so the metric sits flat through every incremental step and then drops
20–30 at once. Under `policy = "sum"` the commit landing a cliff earns a 20–30
point offset for unrelated debt in the same branch — larger than the free pass
the LOC metrics were dropped over.

Changes — `tingle.toml`:

```toml
[[metrics]]
name = "old-subdomain-loc"
type = "line_count"
group = "refactoring"
ranges = ["old-subdomain-modules"]
```

kept next to `old-subdomain-files`.

Verify:

- `tingle stat` → `old-subdomain-loc` equals the summed `wc -l` of the five
  trees.
- Scratch commit moving one module out of `chronology/` into an `event/` path →
  `--diff` shows a proportional LOC drop and −1 file. Discard.

Items 3, 5 and 6 are one `tingle.toml` commit; item 4 rides with it.

## P3 — issue tracker write-up (nothing opened, nothing edited)

### 7. `giant-files` metric (`file_count` + `over_lines`)

Searched: `gh issue list --search` on tingle / file size / giant / split /
"1000 lines" / debt / metric / over_lines / lint. **No existing issue covers a
size ratchet.** The nearest hits are single-file cleanups, not a gate:

- **#746** "Split `mills/timetable.py` (and its test module) along its three
  service seams" — one instance of the problem (1,036 lines).
- **#699** "Panel URLconf lives under `event/` and owns 15 chronology view
  modules" — sprawl, but structural, not size.
- **#675** "Agent readiness dashboard: progress against the 84-signal rubric" —
  where a new metric would show up, not where it is decided.

So: **a new issue**, and a comment on #746 pointing at it once it exists
(#746 becomes the first payment against the new metric, not a duplicate).

Confirmed today: `over_lines` is a real `file_count` option in tingle 0.4.1
(`tingle list --types`: "with `over_lines`, only those strictly longer than
that many lines"), and 7 files under `src/` exceed 1,000 lines —
`links/db/django/models.py` 1,790; `adapters/web/django/views.py` 1,773;
`pacts/legacy.py` 1,635; `gates/web/django/chronology/views.py` 1,247;
`gates/web/django/chronology/panel/views/google_docs_import.py` 1,213;
`links/db/django/repositories/submissions.py` 1,162; `mills/timetable.py`
1,036. Nothing in `mise run check` would notice the 8th.

What the new issue would say:

> **Title:** tingle: ratchet against giant files (`file_count` + `over_lines`)
>
> **Body:** `file_count_diff` counts crossings in both directions, so a file
> pushed past a line threshold scores as new debt and one refactored back under
> it scores as debt paid. The repo has no size gate at all: 7 files under `src/`
> are over 1,000 lines today (list above, measured 2026-08-09) and the 8th would
> land silently.
>
> Proposal — six lines in `tingle.toml`:
>
> ```toml
> [[metrics]]
> name = "giant-files"
> type = "file_count"
> group = "refactoring"
> ranges = ["python-src"]
> over_lines = 1000
> ```
>
> Baseline 7. Existing offenders are grandfathered (the gate is diff-aware);
> only crossing the threshold costs. Pairs with the "halve, don't shard" rule —
> the payment is splitting a file in two along its real seam, not scattering
> helper modules. #746 is the obvious first payment.
>
> Threshold is a judgement call: 1,000 grandfathers 7 files, 800 would
> grandfather ~10 and bite sooner. Open question for the issue, not a blocker.
>
> **Labels:** whatever `tingle`/tooling work usually carries in this repo
> (checked at open time; no `tingle` label exists today).

## Not done

- Nothing implemented, committed, or pushed; no issue opened or edited — as
  asked.
- Line counts and metric values above are measured at triage time and will
  drift; re-run `tingle stat` before acting on item 5–7 numbers.
