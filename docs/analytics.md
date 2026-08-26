# Analytics (PostHog)

Two halves, one project. `prologue.ts` runs in the browser behind a consent
banner; `links/analytics/reporting.py` reports server faults only. The wiring
itself is documented where it lives — `edges/settings.py` for CSP and env,
`links/analytics/identity.py` for how a person is named, `.env.schema` for the
two PostHog origins. This file records the decisions that left no code behind.

## Deliberately not done

- **No `PosthogContextMiddleware`.** It tags events with the visitor's email and
  `$ip` and builds person context — the opposite of the posture the server half
  takes (`$process_person_profile: False`, `disable_geoip: True`). Its
  `process_exception` hook would also only cover views, while the
  `got_request_exception` receiver we use also fires for middleware that raises
  and for a 500 handler that fails.
- **No server-side product analytics.** Ten hand-placed `capture()` calls were
  removed: they duplicated client autocapture and fired regardless of consent.
- **No PostgreSQL data-warehouse source.** Wanted for neither error tracking nor
  identify, and it needs the production DB publicly reachable — Coolify has no
  source-IP allowlist, that lives in the host firewall, and `ufw` does not work
  for Docker-published ports. Revisit only when app-table joins are actually
  wanted, and revise the privacy policy first.
- **No key in `.env.development`.** Dev traffic would land in the project as
  session replays and half-written-code exceptions.
- **One project, not two.** Separate staging and production projects are the
  cleaner split and what PostHog recommends, but the free plan caps the org at
  one. Staging is disambiguated instead: ids are namespaced per deployment and
  every event carries `environment`. Splitting later is a key swap on the
  `staging` GitHub Environment plus deleting `identity.distinct_id`.

## Open

- Add `environment = staging` to the project's test-account filters. Those apply
  to insights only — error tracking, session replay and web analytics each need
  the filter applied separately.
- Events ingested before namespacing have staging and production persons merged
  under bare pks, and no filter separates them.
- `session_recording.maskTextSelector` is `[data-ph-mask]`, which currently
  matches no template. Autocapture does not honour it either — that needs
  `mask_all_text` or the `ph-no-capture` class — and autocapture records clicked
  element text, which on the facilitator and proposal tables is people's names.
