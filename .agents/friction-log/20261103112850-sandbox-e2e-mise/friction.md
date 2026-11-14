---
title: 'Sandbox e2e: mise hk alias fails and ludamus.localhost does not resolve'
severity: 'major'
---

### Expected Behavior

`mise run test:e2e -- <spec>` runs in a Claude web sandbox after the SessionStart hook.

### Current Behavior

Every mise task dies on `cargo:hk@2.7.0: option workflow is not used by the cargo backend`. With `MISE_DISABLE_TOOLS=hk`, Playwright still never detects the :8001 privacy server: it redirects to `ludamus.localhost`, which Node can't resolve (`getaddrinfo ENOTFOUND ludamus.localhost`). A cold `test:e2e:prep` also overruns the 180s webServer timeout.

### Possible Solution

Drop the `workflow` option from the sandbox hk alias; have the SessionStart hook add `127.0.0.1 ludamus.localhost` to /etc/hosts.

### Minimal Reproducible Example

`mise run test:e2e -- propose-reuse --project=chromium-auth` in a fresh sandbox.

### Context

Workaround: `MISE_DISABLE_TOOLS=hk`, add the hosts entry, run `test:e2e:prep` and `test:e2e:serve` by hand before the test run.
