---
title: 'Sandbox e2e: ludamus.localhost does not resolve, privacy webServer never ready'
severity: 'minor'
---

## Expected Behavior

`mise run test:e2e` brings up the :8001 privacy server in a Claude Code web sandbox.

## Current Behavior

`/etc/hosts` only maps `localhost`, so Node gets ENOTFOUND for `ludamus.localhost`. Playwright follows the :8001 302 there, never sees the server as ready, and times out after 180s.

## Possible Solution

Have the SessionStart hook add `127.0.0.1 ludamus.localhost another.ludamus.localhost` to `/etc/hosts`.

## Minimal Reproducible Example

`node -e 'require("dns").lookup("ludamus.localhost", console.log)'` prints ENOTFOUND.

## Context

Verifying a privacy-revocation spec change; cost several 3-minute timeouts.
