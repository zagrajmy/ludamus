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

## Coolify CLI

Install the [Coolify CLI][coolify-cli]. An instance administrator must enable
API Access and permit the operator's IP. Create a short-lived, team-scoped API
token with `read:sensitive` permission, then configure the production context.
This scope exposes logs and may expose secrets, so use the shortest practical
expiry.

```bash
printf "Coolify token: " && read -rs COOLIFY_TOKEN && printf "\n"
coolify context add zagrajmy-production \
  https://arboretum.radekmg.pl \
  "$COOLIFY_TOKEN"
unset COOLIFY_TOKEN
coolify --context zagrajmy-production context verify
```

[coolify-cli]: https://coolify.io/docs/cli/installation

## Triage

1. Record the absolute time, timezone, URL, status, screenshot, and Cloudflare
   Ray ID.
2. Reproduce once without changing production.
3. Query PostHog for events, exceptions, logs, and recordings in a narrow UTC
   window. A missing browser event may mean the response stopped JavaScript
   before PostHog loaded; it does not prove downtime.
4. Query Cloudflare by hostname, time, and Ray ID. Check edge or WAF events,
   configuration changes, and DNS or proxy anomalies.
5. If both surfaces end at the origin boundary, inspect Coolify runtime and
   deployment logs:

   ```text
   coolify --context zagrajmy-production app logs \
     wk4p10un5xghmkgrqlsd7jda --lines 200 --show-timestamps
   coolify --context zagrajmy-production app deployments logs \
     wk4p10un5xghmkgrqlsd7jda --lines 200
   ```

6. Even if the investigation fails, delete the local Coolify context:

   ```text
   coolify context delete zagrajmy-production
   ```

   Then revoke the token under **Keys & Tokens → API Tokens** in Coolify.

## MCPs

- **PostHog:** pinned read-only to the Zagrajmy project and limited to
  insights, event metadata, SQL queries, error tracking, logs, and replay. The
  project timezone is UTC; recordings exist only when capture was enabled.
- **Cloudflare:** the API server is broad; the OAuth grant is the safety
  boundary. Authorize only the account and read scopes needed for the incident.

Report facts, bounded incident times, missing evidence, uncertainty, and the
next discriminating check. Never turn an event gap into a root-cause claim.

## Autofix loop

A production error above a threshold starts a Claude Code routine, which
investigates against both feeds and opens a draft pull request. The routine
is `trig_01XXP25QE6qpGyMXJEhupYKk`, named "Production error autofix". It
never merges, never deploys, and never writes through a connector; when a fix
would touch a guarded path, or it cannot reproduce the failure, it reports
instead of guessing.

Four parts, in the order they have to be wired:

1. **Detection.** `observability.issues.enabled` in a Worker's Wrangler
   configuration, and PostHog error tracking for Django. Issues only sees
   traffic from the moment it is switched on, so enable it before a Worker's
   first deploy.
2. **An API trigger on the routine.** Add it at
   [claude.ai/code/routines][routines] — **Edit** → **Select a trigger** →
   **Add another trigger** → **API**, then **Generate token**. The token is
   shown once. The CLI cannot create or revoke it.
3. **Connectors on the routine.** A routine created through the API stores
   none, and a session without them cannot query either feed. Add the
   Cloudflare and PostHog connectors on the same edit form, and remove every
   other one: a run may call any tool of an included connector, **including
   writes, without asking**. The routine's prompt forbids writes, but the
   connector list is the only enforcement.
4. **The destinations.** In Cloudflare, create an Issues automation with the
   Claude Code integration and paste the routine ID and token. In PostHog,
   point an error-tracking alert at a webhook destination:

   ```text
   POST https://api.anthropic.com/v1/claude_code/routines/<routine-id>/fire
   Authorization: Bearer <routine-token>
   anthropic-beta: experimental-cc-routine-2026-04-01
   anthropic-version: 2023-06-01
   {"text": "<the alert body>"}
   ```

The `text` field is freeform and reaches the routine wrapped as untrusted
data, so the routine's prompt has to name it to act on it at all. Treat the
token as a production credential: anyone holding it can start a run.

Two limits bound an error storm without extra plumbing: 30 fires per hour for
this routine, and 100 per hour across the account. Runs draw down the same
subscription usage as interactive sessions.

Set a threshold high enough that a single flaky request cannot start a run.
Cloudflare's minimum occurrence threshold is 1, which is almost never what you
want.

[routines]: https://claude.ai/code/routines
