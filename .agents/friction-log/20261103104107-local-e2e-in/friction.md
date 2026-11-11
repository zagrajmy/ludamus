---
title: 'Local e2e in the sandbox times out on :8001 because ludamus.localhost does not resolve'
severity: 'minor'
---

## Expected Behavior

Playwright sees the :8001 privacy server ready and runs the specs.

## Current Behavior

Playwright waits 180s for webServer and fails: :8001 answers 302 to ludamus.localhost:8001, which getaddrinfo cannot resolve in the container, so the readiness probe never succeeds.

## Possible Solution

Add `127.0.0.1 ludamus.localhost` to /etc/hosts in the session-start hook, or point the probe at a non-redirecting URL.

## Minimal Reproducible Example

`mise run test:e2e -- tests/dynamic-fields.spec.ts --project=chromium` in a Claude web sandbox.

## Context

Worked around by appending the hosts entry by hand.

2026-11-08: recurred in a Claude Code cloud sandbox. `mise run test:e2e` timed
out after 180 s waiting for the privacy web server, because
`http://localhost:8001/` redirects to `ludamus.localhost:8001` and the
sandbox resolver maps no `*.localhost` subdomain; adding
`127.0.0.1 ludamus.localhost` to /etc/hosts fixed it again.
