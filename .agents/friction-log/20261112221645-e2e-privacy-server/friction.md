---
title: 'E2E privacy server never becomes ready: Node cannot resolve ludamus.localhost in the sandbox'
severity: 'minor'
---

### Expected Behavior

`mise run test:e2e -- dashboard.auth.spec.ts` starts both web servers and runs the specs.

### Current Behavior

In a Claude web sandbox, Playwright times out after 180s waiting for the :8001 privacy server. With `DEBUG=pw:webserver` the readiness check shows `getaddrinfo ENOTFOUND ludamus.localhost`: :8001 redirects to `ludamus.localhost:8001`, and Node's resolver does not map `*.localhost` to loopback here (Chromium does).

### Possible Solution

Add `127.0.0.1 ludamus.localhost` to `/etc/hosts` in the sandbox setup, or point the :8001 readiness `url` at a path that does not redirect.

### Minimal Reproducible Example

`node -e "require('dns').lookup('ludamus.localhost', console.log)"` prints `ENOTFOUND` in the sandbox. Workaround: `echo '127.0.0.1 ludamus.localhost' >> /etc/hosts`.

### Context

Verifying a dashboard layout change before merge; cost two server timeouts.
