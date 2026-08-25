# PostHog setup — outstanding work

Server-side error tracking is wired; what is left is mostly verification and
one copy change.

## Shape of the integration

- **Client** (`prologue.ts`) — pageviews, session replay, JS exceptions.
  Consent-gated in localStorage; PostHog is never initialized before the
  visitor accepts. Identifies by user pk, resets on logout.
- **Server** (`links/analytics/reporting.py`) — faults only, reported from a
  `got_request_exception` receiver. Tagged with the user pk so a report is
  traceable, but always `$process_person_profile: False` and
  `disable_geoip: True`: no person is built, no properties accumulate, no
  location is derived. The server cannot read localStorage, so a report has to
  be safe to send for someone who declined.
- **No server-side product analytics.** The wizard's ten hand-placed
  `capture()` calls were removed. They duplicated client autocapture and fired
  regardless of consent.

## Blocking

- [x] **Add the server half to the privacy policy.** Done on #787 as §3.5,
      legitimate interest, with §4.2 corrected — it claimed consent covered
      everything sent to PostHog.
- [x] **Retarget the banner's privacy link when #787 lands.** Done on #787.
      The footer's e2e assertion pins the same `privacy-policy` URL name, so a
      rename fails loudly there rather than silently emptying the banner href.
- [ ] **Screenshot the banner** for the PR description. It only renders with
      `POSTHOG_API_KEY` set and no choice stored, so set a key in `.env.local`
      first, then `mise run shots -- /`.
- [ ] **Set `POSTHOG_API_KEY` on the `production-coolify` GitHub Environment**
      — the one `deploy-production-coolify.yml` names, not `production`, which
      belongs to the legacy VPS workflow and would be a no-op. Nothing breaks
      if it is missed: the bulk PATCH below leaves the stored value in place,
      so the app keeps running on a key no longer declared in the repo.
- [ ] **Delete `POSTHOG_API_KEY` from the staging Coolify app by hand.** The
      sync is `PATCH .../envs/bulk`, which upserts: a key the payload omits
      keeps whatever value is already stored, and staging's was written by
      every deploy before this. Until it is removed, staging keeps reporting
      into the production project.
- [ ] **Delete the staging and test events already ingested,** or accept them.
      Person records are shared across the two environments, so no filter
      separates them cleanly.

## Verification before merge

- [ ] Trigger a controlled exception outside production; confirm it reaches
      error tracking with a stack trace and the pk as distinct id.
- [ ] Exercise logout → login as a different user; confirm the client distinct
      id follows and does not merge the two people.
- [ ] Load with CSP enforced, check the console for violations.
- [ ] Confirm the dashboard fills after real traffic; empty tiles before first
      ingestion are expected.

## Deployment

The Coolify workflows (`deploy-coolify.yml`, shared by staging and
production) build their env payload from GitHub Environment vars and secrets
alone. `.env.production` is read only by the legacy VPS path — varlock when
`ENV=production`, and `docker/compose/prod.yaml`'s `env_file` ahead of
`.env.local`. Django reads only `os.environ`, so the file does nothing until
one of those loads it.

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
- **No `PosthogContextMiddleware`.** It tags events with the visitor's email
  and `$ip` and builds person context, which is the opposite of the posture
  above. Its `process_exception` hook would also only cover views, while
  `got_request_exception` also fires for middleware that raises and for a 500
  handler that fails.

## Environments

`phc_CpBrrTFf…` is the production project, and the only project in the org.

- **Production on Coolify** takes `POSTHOG_API_KEY` from the
  `production-coolify` GitHub Environment, like every other value that
  workflow syncs. The legacy VPS still reads it from `.env.production`
  through compose.
- **Staging** has no key, so analytics is off there. Give it one only by
  creating a second PostHog project — never by reusing production's. Both
  halves identify by bare Django pk (`context_processors.py`,
  `links/analytics/reporting.py`), unqualified by environment, so one key
  across two databases makes staging's user 42 and production's user 42 a
  single PostHog person.
- **Tests** pin the key empty in `.env.test` and `.env.e2e`, and
  `tests/conftest.py` fails collection if one is set anyway. The integration
  suite also stubs the client through an autouse fixture, but e2e runs a real
  server that nothing patches, which is the path the pins exist for.
