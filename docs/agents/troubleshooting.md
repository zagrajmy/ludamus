# Production troubleshooting

`.mcp.json` configures project-scoped PostHog and the supported Cloudflare API
server. Compatible clients load it from the repository root. Authenticate with
OAuth on first use. For Cloudflare, authorize only the Zagrajmy account and
required read scopes; never grant write scopes. Never commit tokens.

Claude Code on the web loads `.mcp.json`, but `zagrajmy-posthog` and
`zagrajmy-cloudflare` stay unauthenticated: a cloud session cannot run the
OAuth flow. Use the claude.ai connectors instead — `mcp__PostHog__exec` and
`mcp__Cloudflare_Developer_Platform__*`. Neither carries `.mcp.json`'s pins:
both can write, and the PostHog one spans every project. Select PostHog
project 251811 (Zagrajmy), pass the Zagrajmy `account_id`
(`add2b427b034a6073f63a849af7de160`) to Cloudflare, and make read-only calls
only on both.

## Triage

1. Record the absolute time, timezone, URL, status, screenshot, and Cloudflare
   Ray ID.
2. Reproduce once without changing production.
3. Query PostHog in a narrow UTC window: origin logs, exceptions, events, and
   recordings. A missing browser event may mean the response stopped
   JavaScript before PostHog loaded; it does not prove downtime.
4. Query Cloudflare by hostname, time, and Ray ID. Check edge or WAF events,
   configuration changes, and DNS or proxy anomalies.

Report facts, bounded incident times, missing evidence, uncertainty, and the
next discriminating check. Never turn an event gap into a root-cause claim.

## Origin logs

Every INFO-and-up line the app writes reaches PostHog Logs as service
`ludamus` (`links/analytics/log_shipping.py`), with `deployment.environment`
`production` or `staging`. Each `extra=` field is a filterable attribute.

The request line is the wide event (logger `wide_event`): `ray_id`, `commit`,
`worker`, `method`, `path` (redacted), `route`, `view`, `status`, `outcome`,
`duration_ms`, `db_queries`, `db_ms`, `sphere_id`, `user_id`, `language`,
`htmx`, and on a fault `error_type`. The traceback is on the `django.request`
line beside it. `ray_id` is Cloudflare's `CF-Ray`, so the id on a user's
error page finds the request:

```json
{"query": {"serviceNames": ["ludamus"], "dateRange": {"date_from": "-1d"},
 "filterGroup": [{"key": "ray_id", "type": "log_attribute",
                  "operator": "exact", "value": "9c1a0b2d3e4f5a6b-WAW"}]}}
```

That is the `query-logs` input. Static assets and `/healthz/` emit nothing.

## Coolify, with a human

Go to Coolify only when PostHog has no lines for the window: ingestion down,
a crash before logging starts, or a failed deploy. Its log endpoints need
`read:sensitive`, which also reads every secret in the team, so no agent holds
that token. A maintainer runs it from their machine with a short-lived token
and revokes it after:

```text
coolify --context zagrajmy-production app logs \
  wk4p10un5xghmkgrqlsd7jda --lines 200 --show-timestamps
coolify --context zagrajmy-production app deployments logs \
  wk4p10un5xghmkgrqlsd7jda --lines 200
```

Setup: install the [Coolify CLI](https://coolify.io/docs/cli/installation),
then add the context without leaving the token in shell history:

```bash
printf "Coolify token: " && read -rs COOLIFY_TOKEN && printf "\n"
coolify context add zagrajmy-production https://arboretum.radekmg.pl \
  "$COOLIFY_TOKEN" && unset COOLIFY_TOKEN
```
