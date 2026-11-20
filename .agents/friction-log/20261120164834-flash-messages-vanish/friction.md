---
title: 'Flash messages vanish on sphere subdomains in local e2e'
severity: 'minor'
---

### Expected Behavior

A flash message set by a POST on a sphere subdomain (e.g. `crew.localhost:8000`) shows on the page it redirects to, in local e2e as it does on `localhost:8000`.

### Current Behavior

`.env.e2e` sets `SESSION_COOKIE_DOMAIN=".localhost"`, and Django's cookie message storage uses that domain. Chromium treats `localhost` as a public suffix and drops a `Domain=.localhost` cookie set by `crew.localhost`, so the `messages` cookie never reaches the next request and no flash renders. The context jar shows only the host-only `sessionid`/`csrftoken` cookies. On `localhost:8000` itself the cookie is kept, which is why existing flash assertions pass there.

### Possible Solution

Assert flash messages in e2e on the root host only, or leave `SESSION_COOKIE_DOMAIN` unset for e2e if no spec needs a session shared across `*.localhost`.

### Minimal Reproducible Example

As the crew manager, POST any form that calls `messages.warning` and redirects on `crew.localhost:8000` (e.g. Connect Stripe on `/panel/event/crew-open-night/tickets/` with no Stripe key). The server logs the refusal, the redirected page has no `[data-flash]`, and `context.cookies()` has no `messages` cookie.

### Context

Hit while screenshotting the no-Stripe Connect warning for PR #1562; the server side was correct, only the browser dropped the cookie.
