# PostHog setup — outstanding work

Server-side error tracking is wired; what is left is mostly verification and
one copy change.

## Shape of the integration

- **Client** (`prologue.ts`) — pageviews, session replay, JS exceptions.
  Consent-gated in localStorage; PostHog is never initialized before the
  visitor accepts. Identifies by user pk, resets on logout.
- **Server** (`gates/web/django/analytics.py`) — faults only, reported from a
  `got_request_exception` receiver. Tagged with the user pk so a report is
  traceable, but always `$process_person_profile: False` and
  `disable_geoip: True`: no person is built, no properties accumulate, no
  location is derived. The server cannot read localStorage, so a report has to
  be safe to send for someone who declined.
- **No server-side product analytics.** The wizard's ten hand-placed
  `capture()` calls were removed — they duplicated client autocapture and fired
  regardless of consent.

## Blocking

- [ ] **Banner copy (PL + EN).** It currently promises "Nothing is stored
      before you agree", which is no longer literally true: fault reports carry
      the user pk regardless of the choice. Rework to separate error reports
      from analytics, and update the privacy policy flatpage to match. Use the
      `product-design` skill; `session` → "punkt programu" and the rest of the
      glossary in CLAUDE.md apply.
- [ ] **Verify `worker-src blob:`.** The wizard added it to `CSP_POLICY` with
      nothing establishing it was needed. Run `tests/e2e/csp-violations.spec.ts`
      with it removed; if the suite stays green, drop it. A blocked SDK queues
      events without sending them, so this fails silently either way.

## Verification before merge

- [ ] Trigger a controlled exception outside production; confirm it reaches
      error tracking with a stack trace and the pk as distinct id.
- [ ] Exercise logout → login as a different user; confirm the client distinct
      id follows and does not merge the two people.
- [ ] Load with CSP enforced, check the console for violations.
- [ ] Confirm the dashboard fills after real traffic; empty tiles before first
      ingestion are expected.

## Deployment

`.env.production` is committed (public values only) and listed in
`docker/compose/prod.yaml`'s `env_file` ahead of `.env.local`. It has to be
listed explicitly because the container runs no varlock — varlock validates
`.env.local` on the CI runner before upload, and the host's compose CLI just
reads both files.

- [ ] **The Coolify path does not pick this up.** `.dockerignore` excludes
      `**/.env.*`, so `.env.production` is not in the image, and
      `deploy-coolify.yml` has no materialization step — Coolify holds env in
      its own UI. Set `POSTHOG_API_KEY` there before the cutover, or that
      deploy silently runs with analytics off.

## Settled

- **`POSTHOG_HOST`** is not set anywhere per-environment; `.env.schema` and
  `settings.py` already default it to the EU endpoint. Set it only when a
  first-party reverse proxy exists.
- **No key in `.env.development`.** Dev traffic would land in the project as
  session replays and half-written-code exceptions.
- **No PostgreSQL data-warehouse source.** It is wanted for neither error
  tracking nor identify, and it needs the production DB publicly reachable —
  Coolify has no source-IP allowlist, that lives in the cloud/host firewall,
  and `ufw` does not work for Docker-published ports. Revisit only when app
  table joins are actually wanted, and revise the privacy policy first.
- **No `PosthogContextMiddleware`.** It cannot see view exceptions — Django
  turns those into a response before they reach it — which is why the
  `got_request_exception` receiver exists instead.

## Open question

- Is `phc_CpBrrTFf…` the production project, or should production get its own
  separate from any dev/staging project?
