# Production troubleshooting

`.mcp.json` configures project-scoped PostHog and the supported Cloudflare API
server. Compatible clients load it from the repository root. Authenticate with
OAuth on first use. For Cloudflare, authorize only the Zagrajmy account and
required read scopes; never grant write scopes. Never commit tokens.

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
