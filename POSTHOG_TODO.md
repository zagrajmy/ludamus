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
- [x] **Set `POSTHOG_API_KEY` on the `production-coolify` and `staging` GitHub
      Environments.** Both carry the project key. `production-coolify` is the
      one `deploy-production-coolify.yml` names, not `production`, which belongs
      to the legacy VPS workflow and would be a no-op.
- [ ] **Add `environment = staging` to the project's test-account filters**, and
      turn the default on — `test_account_filters_default_checked` is unset, so
      insights do not apply them until it is. Staging shares the project because
      the plan allows one; a second project needs a card. Test-account filters
      cover insights, not error tracking, session replay or web analytics, so
      those keep needing the filter by hand.
- [ ] **Clean up the events ingested before namespacing.** Staging and
      production persons captured under bare pks are already merged, and no
      filter separates them — the `environment` property only exists on events
      sent after this lands.

## Verification before merge

- [ ] Trigger a controlled exception outside production; confirm it reaches
      error tracking with a stack trace and the pk as distinct id.
- [ ] Exercise logout → login as a different user; confirm the client distinct
      id follows and does not merge the two people.
- [ ] Load with CSP enforced, check the console for violations.
- [ ] Confirm the dashboard fills after real traffic; empty tiles before first
      ingestion are expected.

## Deployment

The Coolify workflows (`deploy-coolify.yml`, shared by staging and production)
build their env payload from GitHub Environment vars and secrets alone.
`.env.production` is read only by the legacy VPS path — varlock when
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

`phc_CpBrrTFf…` is the only project the plan allows, so staging reports into
it too. What keeps the two apart is the distinct id, not the key.

`links/analytics/identity.py` namespaces every id by deployment, and both
halves use it — `context_processors.analytics` for the browser,
`reporting.report_exception` for the server. Production keeps bare pks so
persons captured before namespacing keep their timelines; every other
deployment is prefixed. Without that, staging's user 42 and production's user
42 are one PostHog person, because each database runs the same schema with its
own sequence.

Events also carry an `environment` property — added in `prologue.ts`'s
`before_send`, set explicitly on server reports — so staging traffic can be
filtered out of production dashboards instead of merely being traceable. It
lives in the client config rather than a super property because `reset()`
clears super properties, and `reset()` is what a logout or a withdrawn consent
runs.

Tests never send: `.env.test` and `.env.e2e` pin the key empty, and
`tests/conftest.py` fails collection if one is set anyway. The integration
suite also stubs the client through an autouse fixture, but e2e runs a real
server that nothing patches, which is the path the pins exist for.
