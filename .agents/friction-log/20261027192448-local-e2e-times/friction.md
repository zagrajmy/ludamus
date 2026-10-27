---
title: 'Local e2e times out on the privacy web server: ludamus.localhost does not resolve in web sandboxes'
severity: 'minor'
---

### Expected Behavior

`npx playwright test` in a Claude Code web sandbox starts both e2e web servers and runs the specs.

### Current Behavior

The second web server (`test:e2e:serve:privacy`, port 8001) answers 302 to `http://ludamus.localhost:8001/`, which the container cannot resolve (no systemd-resolved). Playwright waits 180 s and fails with "Timed out waiting 180000ms from config.webServer" before any test runs.

### Possible Solution

Add `127.0.0.1 ludamus.localhost` to /etc/hosts, and say so in docs/agents/sandbox.md.

### Minimal Reproducible Example

`getent hosts ludamus.localhost` prints nothing; `curl -I localhost:8001/` redirects there.

### Context

Hit while running tests/e2e/tests/parley.auth.spec.ts on the parley branch.
