# Analytics (PostHog)

Two halves, one project. `prologue.ts` runs in browser behind consent banner.
`links/analytics/reporting.py` reports server faults only.

Wiring documented where it lives: `edges/settings.py` for CSP and env,
`links/analytics/identity.py` for how person named, `.env.schema` for the two
PostHog origins. This file holds decisions that left no code behind.

## Deliberately not done

- **No `PosthogContextMiddleware`.** Tags events with visitor email and `$ip`,
  builds person context. Opposite of what server half does
  (`$process_person_profile: False`, `disable_geoip: True`). Its
  `process_exception` covers views only; our `got_request_exception` receiver
  also fires for middleware that raises and for a 500 handler that fails.
- **No server-side product analytics.** Ten hand-placed `capture()` calls
  removed — duplicated client autocapture, fired regardless of consent.
- **No PostgreSQL data-warehouse source.** Wanted for neither error tracking nor
  identify. Needs production DB publicly reachable: Coolify has no source-IP
  allowlist (lives in host firewall), `ufw` does not work for Docker-published
  ports. Revisit when app-table joins actually wanted. Revise privacy policy
  first.
- **No key in `.env.development`.** Dev traffic would land in project as session
  replays and half-written-code exceptions.
- **One project, not two.** Separate staging/production projects are the cleaner
  split and what PostHog recommends, but free plan caps org at one. Staging
  disambiguated instead: ids namespaced per deployment, every event carries
  `environment`. Splitting later = key swap on `staging` GitHub Environment plus
  deleting `identity.distinct_id`.

## Open

- Add `environment = staging` to project test-account filters. Applies to
  insights only — error tracking, session replay, web analytics each need it
  separately.
- Events ingested before namespacing have staging and production persons merged
  under bare pks. No filter separates them.
- `session_recording.maskTextSelector` is `[data-ph-mask]`, matches no template.
  Autocapture ignores it anyway — needs `mask_all_text` or `ph-no-capture` class
  — and autocapture records clicked element text, which on facilitator and
  proposal tables is people's names.
