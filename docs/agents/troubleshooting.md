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

App log lines (INFO+) are in PostHog Logs, service `ludamus`. The request line
is logger `wide_event`; its `ray_id` is Cloudflare's `CF-Ray`, which carries a
location suffix the user's error page may omit, so match by prefix. Its
traceback, on the `django.request` line, has no `ray_id`: find it by path and
time. Find a request with `query-logs`:

```json
{"query": {"serviceNames": ["ludamus"], "dateRange": {"date_from": "-1d"},
 "filterGroup": [{"key": "ray_id", "type": "log_attribute",
                  "operator": "starts_with", "value": "9c1a0b2d3e4f5a6b"}]}}
```

## Coolify, with a human

When PostHog lacks the lines you need (ingestion down, crash at boot, failed
deploy). Its log API needs `read:sensitive`, which also reads secrets, so a
maintainer runs it with a short-lived token:

```text
coolify --context zagrajmy-production app logs \
  wk4p10un5xghmkgrqlsd7jda --lines 200 --show-timestamps
```
