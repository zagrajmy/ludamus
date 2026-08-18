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

- [ ] **Add the server half to the privacy policy.** PR #787 moves the policy
      into `src/ludamus/content/privacy-policy.md` and adds a §3.4 covering
      analytics, but deliberately only the client side: the fault reporter does
      not exist on that branch, and describing processing that does not happen
      yet is the same defect §3.2 carried for ten months. Whoever merges this
      second adds it — fault reports go out regardless of consent, carrying the
      account pk and request path, building no person and deriving no location.
- [ ] **Retarget the banner's privacy link when #787 lands.** It deletes
      flatpages, so `{% url 'django.contrib.flatpages.views.flatpage'
      url='/privacy-policy/' %}` in `components/consent-banner.html` becomes a
      NoReverseMatch. The replacement is `{% url 'privacy-policy' %}`.
- [ ] **Screenshot the banner** for the PR description. It only renders with
      `POSTHOG_API_KEY` set and no choice stored, so set a key in `.env.local`
      first, then `mise run shots -- /`.

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

`.dockerignore` now un-ignores `.env.production` specifically, and
`deploy-coolify.yml` sources it before building the env payload it PATCHes to
Coolify's API, so both deploy paths read the same committed file. Django itself
reads only `os.environ` (no `read_env`), so the file shipping inside the image
does nothing on its own — something has to load it, which is what the compose
`env_file` and the Coolify sourcing step do.

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

## Open question

- Is `phc_CpBrrTFf…` the production project, or should production get its own
  separate from any dev/staging project?
