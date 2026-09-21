# Production troubleshooting

`.mcp.json` configures `zagrajmy-posthog` and `zagrajmy-cloudflare`.
Compatible clients load it from the repository root. Authenticate with OAuth
on first use, grant read access, and never commit tokens.

## Triage

1. Record the absolute time, timezone, URL, status, screenshot, and Cloudflare
   Ray ID.
2. Reproduce once without changing production.
3. Query PostHog for events, exceptions, logs, and recordings in a narrow UTC
   window. A missing browser event may mean the response stopped JavaScript
   before PostHog loaded; it does not prove downtime.
4. Query Cloudflare by hostname, time, and Ray ID. Identify the security rule
   or request status, then distinguish an edge response from an origin response.
5. If both surfaces end at the origin boundary, inspect Coolify's application
   and deployment logs.

## MCPs

- **PostHog:** pinned read-only to the Zagrajmy project. Use it for browser
  events, exceptions, recordings, and ingested logs. The project timezone is
  UTC; recordings exist only when capture was enabled.
- **Cloudflare:** use it for DNS, proxy, WAF, security events, and request
  analytics. Grant only the account and read scopes needed for the incident.

Report facts, bounded incident times, missing evidence, uncertainty, and the
next discriminating check. Never turn an event gap into a root-cause claim.
