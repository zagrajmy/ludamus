# PostHog setup — outstanding work

Notes from the PostHog Django wizard's closing checklist, filtered against
this repo. Checkpoint commits: `1e7ef223` (client identify), `1a761356`
(wizard output, unreviewed).

## Blocking — must land before merge

- [ ] **Consent gate on server-side capture.** `enable_exception_autocapture`
      and every `capture()` call fire regardless of the banner choice. The
      banner promises "Nothing is stored before you agree", so a visitor who
      declines currently still emits `user_logged_in`, `party_created`,
      `encounter_rsvp_created`. Gate on the consent cookie, or narrow
      server-side to exceptions and reword the banner — reliability telemetry
      is a different claim than analytics.
- [ ] **Drop the `RuntimeError` in `apps.py` `ready()`.** It aborts startup
      under `DEBUG` when the key is unset, which breaks `mise run start` for
      anyone without a key. It is also why the wizard put a live key in
      `.env.development`.
- [ ] **Remove the four `from ludamus.adapters` imports in `gates/`.**
      `tingle.toml` counts that exact pattern in that exact range, so
      `mise run check` fails. Init belongs in `gates/`, not legacy `adapters/`.
- [ ] **Delete the two `# ruff: ignore[...]` comments.** Prohibited by
      CLAUDE.md without per-case approval, and malformed — they suppress
      nothing.
- [ ] **Fix server-side identity.** `identify_context()` in a `user_logged_in`
      receiver only tags the login request. Every later request's events go
      out unattributed. Identify from `request.user` inside the request
      context instead.
- [ ] **Re-check the ten hand-placed `capture()` calls.** Unrequested, and
      they duplicate client autocapture. Keep only what the client cannot see.

## From the wizard's checklist — applies here

- [ ] Full production build (`mise run check`); the wizard verified
      compilation and Ruff only. Focus: `adapters/web/django/apps.py`,
      `edges/settings.py`.
- [ ] Full test suite; instrumented call sites may need fixtures. Focus:
      `crowd/auth.py`, `crowd/views.py`, `chronology/views.py`,
      `notice_board/views.py`. No tests exist for the consent gate or the
      identify path — add both.
- [ ] Load the app with CSP enforced and check for violations. The wizard
      added `worker-src blob:` (replay worker) with nothing verifying it;
      `tests/e2e/csp-violations.spec.ts` enforces the real policy. A blocked
      SDK queues events without sending them, so this fails silently.
- [ ] Exercise the returning-authenticated-visitor path; confirm the distinct
      id stays the pk across logout/login and does not fall back to an
      anonymous id.
- [ ] Trigger a controlled Django exception outside production and confirm it
      reaches error tracking. Note the known limitation:
      `PosthogContextMiddleware` does not catch view exceptions — Django turns
      them into a response before they propagate. Needs `got_request_exception`
      or a `process_exception` hook.
- [ ] Deploy with the key set, exercise each instrumented action, confirm the
      events arrive. Empty dashboard tiles before first ingestion are expected.

## From the wizard's checklist — does not apply

- **"use `.env.example` as the reference"** — this repo has no `.env.example`.
  The schema is `.env.schema` (varlock), with `.env.{ENV}` as committed
  per-environment baselines and `.env.local` gitignored.
- **"set both variables in every deploy environment"** — `POSTHOG_HOST`
  already defaults to `https://eu.i.posthog.com` in `.env.schema` and
  `settings.py`. Set it only when a first-party reverse proxy exists.
- **"Connect PostgreSQL through the browser flow"** — that is the data
  warehouse source, wanted for neither error tracking nor identify. It needs
  the production DB publicly reachable, and Coolify has no source-IP
  allowlist (that lives in the cloud/host firewall; `ufw` does not work for
  Docker-published ports). Revisit only when app-table joins are actually
  wanted, and revise the privacy policy first.

## Open questions

- Is `phc_CpBrrTFf…` (the key the wizard wrote into `.env.development`) the
  production project, or a separate dev project?
- Should `.env.development` carry a key at all? Dev traffic would land in the
  project as session replays and half-written-code exceptions.
- Keep `.claude/skills/integration-django/` (installed by the wizard,
  currently untracked)?
