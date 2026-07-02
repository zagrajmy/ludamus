# Improvement Plan

Deep audit of ludamus performed 2026-06-10 at commit `337cdde7` (branch
`fable-improve`, clean tree). Scope: whole repo, all nine audit categories,
plus triage of the 9 open PRs and alignment with the
[Clanker's Kapitularz Umbrella (#326)](https://github.com/zagrajmy/ludamus/issues/326).
Eight parallel audit agents ran; every finding below was then re-verified by
reading the cited code directly. Detailed executor-ready plans for the top
findings live in [`plans/`](plans/README.md).

**Not audited**: `tests/e2e` internals beyond auth strategy, `src/ludamus/client`
JS in depth, Docker/deploy configs beyond settings, git history before ~3 months.

---

## 1. Open-PR triage (do this before anything else)

The cheapest wins in this repo right now are sitting in the PR queue. Several
audit findings are *already fixed* in open PRs; landing them changes the
baseline for everything else.

| PR | State | Recommendation |
|----|-------|----------------|
| **#359** fix(enrollment): lock anonymous enroll/cancel, promote waitlist | draft, APPROVED, codecov patch failing | **Land first.** Fixes three real race conditions the audit independently confirmed (anonymous overbooking via unlocked `is_full`, stuck waitlist after anonymous cancel, 500 on concurrent cancel via `next()` without default at `views.py:1489`). Only coverage gates block it — add the missing patch tests. |
| **#362** content change audit log | APPROVED, checks green | **Merge.** Unblocks the umbrella's "undo last change" (S) task, which shares the changelog pattern. |
| **#334** public /print page | APPROVED, only staging-deploy dispatch failed | **Merge** (re-run the dispatch). Closes #332. |
| **#337** waiting-list offer-and-claim | active (updated today) | Coordinate with #359 — **both touch promotion logic**. Decide merge order explicitly (suggest #359 first, rebase #337) or one will silently revert the other's locking. Implements #327. |
| **#234** remove Tag legacy (code-side) | draft, checks green | **Undraft + merge**, then schedule the deferred schema-drop migration. Until then `Tag`/`TagCategory` (models.py:560-590) are dead weight and `tags__category` is still prefetched on the hottest page (views.py:813). |
| **#361** Kapitularz import skeleton | draft, CI red, changes requested, +11k lines | The umbrella's "google import (M)". Too big to review well — consider splitting (recipe model / importer / panel UI). Don't let it bitrot; it blocks Konwencik sync de-risking per the umbrella DAG. |
| **#248** proposal description → repo | tests failing, from May | Rebase or close — 7 files, strangler-fig step; cheap to revive. |
| **#261** mise task syntax + parallelize | draft, CI red | Revive together with the `jobs = 1` question (DX-2 below). |
| **#260** view transitions | draft experiment | Park; no action needed. |

---

## 2. Vetted findings

Ordered by leverage (impact ÷ effort, weighted by confidence). ✅ = full plan
written in `plans/`.

| # | Finding | Category | Impact | Effort | Risk | Confidence | Evidence |
|---|---------|----------|--------|--------|------|------------|----------|
| 1 ✅ | **Event page N+1 ×2**: participations loop re-queries per session (`.select_related("user").all()` defeats prefetch), `field_values` never prefetched on `event_sessions` | perf | 2 queries/session on the highest-traffic page; #323 | S | LOW | HIGH | `views.py:1158-1160`, `views.py:1135` vs prefetch at `views.py:812-817` |
| 2 ✅ | **Open redirect in Auth0 flow**: `next` stored in OAuth state and honored at callback without host validation | security | phishing-grade open redirect on login | S–M | MED | HIGH | `views.py:137-161`, `views.py:228-253` |
| 3 | **Enrollment races (anonymous + cancel-500)** | bug | overbooking, stuck waitlists | — | — | HIGH | Fixed by open PR #359 — land it (see §1) |
| 4 ✅ | **Flaky CI from `Faker("slug")`** in 8 factory declarations (unique-column collisions; same bug already fixed once in `bde5be84`) | tests | random red builds, re-run tax | S | LOW | HIGH | `tests/integration/conftest.py:83,108,118,128,146,157,166,192` |
| 5 ✅ | **mills/pacts/inits/specs absent from coverage.xml** despite `source=["src"]` and existing mills unit tests — the 93%/96% gates may not measure the business-logic layer at all | tests/dx | coverage gate blind to services | S (investigate) | LOW | MED | `grep -c mills coverage.xml` → 0; `pyproject.toml [tool.coverage.run]` (`core="ctrace"`, django plugin) |
| 6 ✅ | **Panel-view boilerplate duplicated across ~70 views/13 files** (authors' own TODO markers); umbrella adds 6+ more panel features and an XL permissions retrofit on top of it | tech-debt | every cross-cutting panel change is a 70-site edit | M | LOW | HIGH | `gates/.../panel/views/{cfp,tracks,session_fields,time_slots,venues}.py` headers; `base.py:35-97` |
| 7 | **Strangler-fig migration ~half done**: 18 files on `request.di.uow` (~220 call sites) vs 15 on `request.services`; mixins themselves still call `di.uow` | tech-debt | two parallel injection systems; every feature on legacy code doubles later work | L (program) | MED | HIGH | grep counts; `base.py:49,79-88`; `docs/agents/services-migration.md` |
| 8 | **Membership API failure silently blocks waitlist promotion** (errors swallowed → treated as "no config") | bug | users stuck on waitlist during API outage, invisibly | M | MED | MED | `views.py:1529-1535`, `mills/legacy.py` (~705-735); intersects PR #337's redesign — fold into it |
| 9 | **Tag/TagCategory dead models + hot-page prefetch** | tech-debt | dead schema, admin, repo methods; wasted prefetch | S after PR #234 | LOW | HIGH | `models.py:560-590`, `views.py:813` |
| 10 | **`mise` `jobs = 1`** serializes all 11 lint tasks locally (CI overrides with `--jobs 4`) | dx | slow `mise run check` feedback loop | S | LOW | HIGH | `mise.toml:1-2`; verify it isn't intentional (output interleaving), relates to PR #261 |
| 11 | **No `black` hook in pre-commit** while CI's `prcheck` runs `black-check` → local-pass/CI-fail drift | dx | avoidable CI failures | S | LOW | MED | `.pre-commit-config.yaml` vs `mise.toml` prcheck task |
| 12 | **No pytest-xdist** (TODO.md lists "Isolated/parallel test execution" as open) | dx | CI/test wall-clock | M | MED | HIGH | `pyproject.toml` dev deps |
| 13 | **Dependabot covers pip only** — no npm ecosystem for `src/ludamus/client` or `tests/e2e` | deps | frontend dep/security lag detected manually | S | LOW | HIGH | `.github/dependabot.yml` |
| 14 | **ImageField uploads lack size/type validators** (`Event.logo`, covers) | security | disk exhaustion, oversized uploads | M | LOW | MED | `models.py` ImageFields (~162, 686); GCS storage softens it |
| 15 | **30-day session cookies, CSRF cookie stored in OAuth cache state** | security hygiene | larger hijack window; needless secret in cache | S | LOW | MED | `edges/settings.py` (~304-308), `views.py:158` |
| 16 | **E2E auth bypasses Auth0** via Django admin login (already tracked as #303) | tests | OAuth callback path untested e2e | L | MED | HIGH | `tests/e2e/tests/panel.spec.ts:97-104` |
| 17 | **Migration 0059 reverse is a noop** (tags→fields data migration) | deps/migrations | rollback below 0059 loses data silently | S (document) | LOW | HIGH | `migrations/0059_...py:170-172`; becomes moot once Tag schema drops — document "no rollback past 0059" instead of writing a reverse |
| 18 | **Stale doc claims**: `docs/LOCAL_DEV.md` duplicates `poetry install` (bootstrap already runs it); architecture.md's "some views still use di.uow" understates ~50% | docs | onboarding friction, wrong mental model | S | LOW | HIGH | `docs/LOCAL_DEV.md:4-5`, `tasks.toml:31-49`, grep counts |
| 19 | **`.pylintrc` (681 lines) largely overlaps ruff `select=["ALL"]`** | dx | double lint maintenance + CI time | M | MED | MED | `.pylintrc`, `pyproject.toml:217` — keep only what ruff lacks (e.g. duplicate-code) |
| 20 | **Repo-root clutter**: `coverage.xml`, `.coverage*`, `daemon.log`, sqlite files, `images-plan.gitignored.md` in the working tree | dx | misleads tools and humans (finding 5 was nearly masked by it) | S | LOW | HIGH | `ls` repo root; TODO.md already lists "Clean up internal files" |

### Per-file fix-it notes not worth their own row

- `views.py:1577-1586` filter-then-save with a "get_or_create" comment that
  doesn't match the code — the session `select_for_update` plus the
  `(session, user)` unique constraint make the race mostly theoretical, but
  make the code honest (use `update_or_create`) whenever PR #359/#337 settle.
- `EventPageView._get_session_data` also iterates all enrollment configs per
  session in Python (`models.py` `effective_participants_limit`,
  `is_enrollment_available`) — O(sessions × configs); revisit only if #323 is
  still slow after plan 001.

---

## 3. Rejected findings (don't re-audit these)

Subagent reports that did not survive verification:

- **"Python 2 `except KeyError, ValueError:` syntax error at views.py:283"**
  (reported independently by three agents as a critical bug) — this is **valid
  Python 3.14** (PEP 758 allows unparenthesized multi-exception `except`). The
  module imports fine; the app runs.
- **"Django 6.0.5 with 5 CVEs"** — `poetry.lock` already pins 6.0.6 (bumped in
  commit `723c970d`); the agent audited a stale environment.
- **"Real secrets committed in `.env.local`"** — `.env*.local` is gitignored
  (`.gitignore:136-139`) and not in `git ls-files`; per-developer secrets there
  are the documented design. Tracked `.env.development` contains only
  dev/simulator values.
- **"import-linter not wired into CI"** — it's the `il` task inside
  `mise run check`/`prcheck` (`mise.toml:67-69,105`); CI runs `prcheck`.
- **"Concurrency tests never run in CI (SQLite only)"** — `ci.yml:62-85`
  defines `test-postgres` with a postgres:16 service running `mise run test:postgres`.
- **"CI jobs are sequential"** — no `needs:` between jobs; GitHub Actions runs
  them concurrently.
- **"`.env.docker` referenced by docs but missing"** — the file exists and is tracked.
- **"Authenticated capacity check happens outside the transaction"** —
  `_process_enrollments` re-fetches with `select_for_update()` (`views.py:1473`)
  before validating capacity.
- **"nh3/markdown XSS risk"** — checked: conservative allowlist, correctly configured.

---

## 4. Alignment with the Kapitularz umbrella (#326)

The umbrella's DAG holds up against the code, with three corrections and one
addition — **all applied to issue #326 on 2026-06-10** (status header, in-flight
PR annotations, the *notification infra* foundation node with its DAG edges,
the google-import estimate caveat, and the panel-base-view prerequisite on the
permissions XL):

1. **"google import — importer is a stub" is accurate on main** (`links/google_docs.py`
   has `check()` only; no `run()`/fetch in the integration protocol), but
   PR #361 contains most of the missing skeleton. The umbrella M-estimate is
   right *only if #361 lands*; otherwise it's L.
2. **"confirm program items: `AgendaItem.session_confirmed` exists"** —
   confirmed (`models.py:813`), and it is **completely inert**: set by
   fixtures, rendered in `__str__`, consumed by nothing. The M-estimate is
   safe; the field is genuinely a head start, not a half-built feature.
3. **Waiting list (S)** is in-flight as PR #337 + #359 — but the umbrella's
   "notification" half has no infrastructure at all (no Notification model, no
   queue, no email sending in mills). The same gap blocks **errata channel (L)**
   and **org announcements (M)**. *Notification infra* is now an explicit
   M–L foundation node in the umbrella DAG (`NOTIF --> ERRATA`, dotted edges
   to announcements and the waiting-list notify remainder); the sync-vs-queued
   decision belongs to that node.
4. **Organizer permissions (XL)** — the audit strengthens the umbrella's
   "build early" note: today every panel permission check is one
   `spheres.is_manager()` call duplicated across ~70 views
   (`base.py:40-49`). Plan 005 (boilerplate extraction) makes the eventual
   permission retrofit a one-place change; do it before starting permissions.

Direction options grounded in the code (maintainer's call, not ranked against bugs):

- **JSON API as the Konwencik enabler** — mills services already return
  Pydantic DTOs; a read-only `/api/v1/` (sessions, timetable, enrollments) is
  disproportionately cheap and de-risks both Konwencik sync (L) and any future
  mobile/HTMX work. Evidence: `mills/` DTO-first design; no API namespace in
  any `urls.py`.
- **Soft delete before more audit features** — issue #331 asks for it; today
  50+ FKs cascade (venue delete wipes scheduled sessions + enrollments
  silently), and the new audit logs (#362) record edits but not deletions.
  If the discount subsystem (L) lands on hard-cascade models, retrofitting
  soft delete gets much more expensive.

---

## 5. Guardrails — making the bug classes unrepeatable

Each fix above gets a mechanism so the class of bug can't quietly return.
Detailed in [`plans/006-regression-guardrails.md`](plans/006-regression-guardrails.md)
unless noted.

| Bug class | Guardrail | Mechanism |
|---|---|---|
| N+1 queries (#306, #323) | **Query-auditing test client** | Override the pytest-django `client` fixture with a `Client` subclass that records SQL per request via Django's `execute_wrapper` and fails the test when an identical SELECT repeats >N times. Every existing and future view integration test becomes an N+1 test for free — no new dependency, no per-page opt-in. Escape hatch: `@pytest.mark.allow_duplicate_queries` with a justification comment. Dev-side visibility already exists (django-debug-toolbar); don't add `nplusone` (unmaintained). |
| N+1 on the one page we fixed | **Scaling test** | Plan 001 adds a query-count-constant-in-session-count test for the event page specifically. |
| Flaky factories | **ast-grep rule** | `rules/no-faker-slug.yml` banning `Faker("slug")` — the repo already runs ast-grep custom rules in `mise run check`/`prcheck`, so this is one YAML file. |
| Coverage blind spots | **Coverage canary** | After plan 004 diagnoses the mills gap: one line in the coverage task asserting mills files appear in the report (`coverage report --include="*/mills/*" \| grep -q legacy.py`). A gate that can silently lose whole packages isn't a gate. |
| Open-redirect class | **Regression tests, not static analysis** | CodeQL runs in CI but missed this one — the taint path goes through the cache (store at login, read at callback), which defeats dataflow tracking. Plan 002's five tests are the durable guard; a lint rule can't see this shape. |
| Layering/debt | already guarded | import-linter contracts + vulture + pylint duplicate-code run in `prcheck`; plan 005 removes the standing `# pylint: disable=duplicate-code` exemptions instead of adding more. |

The general principle the repo already half-follows: every gate lives in
`mise run prcheck` so CI and local are the same command. The two gaps were
gates that *measure nothing silently* (coverage) and bug shapes only runtime
can see (queries, redirects) — hence the canary + the auditing client.

## 6. Open-issue triage

All 36 open issues reviewed against the code (claims verified where cheap).
Tiers are recommendations; the umbrella DAG (#326) stays authoritative for
feature sequencing.

**Close or fold — no work needed (6):**

| Issue | Why |
|---|---|
| #332 print page | Closed by PR #334 on merge. |
| #327 waiting-list promotion, #329 remove participant | Both delivered by PR #337 (+#359); verify on merge and close. |
| #15 error reporting | Duplicate of #305 — close as dup. |
| #11 import from program sheet | Superseded by the umbrella's google-import + PR #361; close with a pointer. |
| #9 markdown support | **Substantially shipped**: `render_markdown` (nh3-sanitized, `mills/legacy.py:93`) + `markdown_tags` templatetag used in event/proposal templates. Verify remaining scope (if any) and close. |

**P0 — broken core flow (1):**

- **#339 sphere managers cannot create events** + **#279 dashboard empty state has no creation path** — same root cause, verified: `grep -rn "EventCreate|event-create|create_event" src/ludamus/gates src/ludamus/adapters/web` → zero hits. There is no event-creation view at all; managers must use Django admin. Fix as one M vertical slice (form + service + panel view + empty-state CTA). This blocks every other panel feature for a new sphere — a manager who can't create an event can't use any of them.

**P1 — cheap, high leverage, this cycle (7):**

| Issue | Notes |
|---|---|
| #323 event-page perf | → plan 001. |
| #306 N+1 detection | → plan 006 (test-side enforcement; dev-side = existing debug toolbar). |
| #344 reduce flash messages + #298 logout message | One pass; audit found 130 `messages.*` call sites, so do it as a sweep with a short style rule ("flash only on actions whose result isn't visible on the next page"), not whack-a-mole. #298 is one line inside it. |
| #341 eldritch print time ranges | S bug; do right after PR #334 merges (same templates). |
| #342 session edit modal jank | S–M; popular flow, labeled bug. |
| #340 adopt hk for git hooks | Fold in the pre-commit↔CI drift fix (missing black hook) and the `varlock-scan` node_modules trap found in the audit — adopting hk while leaving drift in place would just port the drift. |
| #305 error tracking (Sentry/Axiom) | M. Prevention-relevant: the audit found silent failure modes (membership API errors swallowed → waitlist promotion silently skipped) that only observability catches in prod. Do before the big Kapitularz event window. |

**P2 — scheduled behind foundations (7):**

| Issue | Notes |
|---|---|
| #304 rate limiting auth/invitations | M; pairs naturally with plan 002 (same views). |
| #303 e2e through auth0 simulator | **Cheaper than it looks**: `@simulacrum/auth0-simulator` already runs in dev (`Procfile.dev:3`, `.env.development:18-19`); the e2e harness needs to reuse, not build, it. Re-estimate M (was L). Unblocks honest testing of plan 002's flow. |
| #331 soft delete sessions | Sequence **before** the umbrella's discount subsystem lands more FKs on hard-cascade models; pairs with the #362 audit-log direction. |
| #343 click tag/host to filter | S–M UX; touches the event page — do after plan 001 so the query guardrail is watching. |
| #281 keyboard alternative for space reordering | M a11y bug; timetable builder. |
| #193 proposal form too-long-value error | S bug; fold into any proposal-form work (e.g. PR #361's orbit). |
| #290 self-host membership API | L; re-evaluate after PR #337 — its promotion redesign may remove the silent-failure pain that motivates this. |

**P3 — epics / parked (deliberately not scheduled):**

#229 conference event layout, #316 semantic search, #10 HTMX migration, #116
"bigger nerds" epic, #23 changelog, #22 venue config, #20 badges, #14 sphere
creation command, #13 slug workflow, #2 renovate dashboard. Two get notes:

- **#155 venues rework** — parked, but it's the named blocker for `TODO(fancysnake): Fix after merging venues` markers sitting in the event-page hot path (`views.py:1105-1145`). If it stays parked another quarter, those TODOs should be re-resolved against reality instead of waiting.
- **#17 production security review** — partially discharged by this audit (open redirect found+planned, secrets handling verified clean, nh3 config verified, session policy noted). Update the issue with what's now covered and what remains (headers/CSP audit, infra review).

## 7. Recommended execution order

**Week 0 — PR queue (no new code):** land #359 → rebase+land #337 → merge #362,
#334 → undraft/merge #234 → decide fate of #248/#261.

**Then, from `plans/` (details in each file):**

1. [`003-deterministic-factory-slugs`](plans/003-deterministic-factory-slugs.md) — S; stabilizes CI for everything after.
2. [`001-event-page-n-plus-one`](plans/001-event-page-n-plus-one.md) — S; user-visible (#323).
3. [`002-oauth-next-open-redirect`](plans/002-oauth-next-open-redirect.md) — S–M; security.
4. [`004-coverage-mills-blindspot`](plans/004-coverage-mills-blindspot.md) — S investigate; restores trust in the 93% gate.
5. [`006-regression-guardrails`](plans/006-regression-guardrails.md) — M; locks in 001/003 (query-auditing test client for #306, ast-grep factory rule). Runs after 001+003 by design — before them it only produces noise.
6. [`005-panel-view-boilerplate`](plans/005-panel-view-boilerplate.md) — M; prerequisite-in-spirit for umbrella panel features and the permissions XL.
7. **#339/#279 event creation in panel** — P0 issue, M vertical slice; first feature to build ON the plan-005 base class (no written plan yet — ask if wanted).

**Standing programs (no single plan):** strangler-fig view migration (finding 7
— keep the one-file-per-PR cadence from `docs/agents/services-migration.md`,
and update architecture.md's progress claim); Tag schema drop after #234;
notification infrastructure decision before announcements/errata.

**Quick wins to fold into any passing PR:** dependabot npm ecosystems (13),
pre-commit black hook (11), `mise` jobs revisit with #261 (10), LOCAL_DEV.md
poetry-install line (18), repo-root artifact cleanup (20).
