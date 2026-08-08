# Plan 002: Validate the OAuth `next` redirect target (close the open redirect)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 337cdde7..HEAD --
> src/ludamus/adapters/web/django/views.py tests/integration/web/crowd/`
> On any in-scope change, compare "Current state" excerpts against live code;
> mismatch = STOP.

## Status

- **Priority**: P1
- **Effort**: S–M
- **Risk**: MED (must not break legitimate cross-subdomain login)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `337cdde7`, 2026-06-10

## Why this matters

The Auth0 login flow accepts a `next` query parameter, stores it in the OAuth
state, and redirects to it after the callback **without validating the host**.
An attacker can send a victim a legitimate-looking
`https://<root>/crowd/auth0/login?next=https://evil.example/` link; after a
successful login the site redirects the victim to the attacker's page —
classic open-redirect, used for phishing ("your session expired, re-enter
your password"). The fix is standard: Django's
`url_has_allowed_host_and_scheme` with an allowlist of this deployment's own
hosts (root domain + sphere subdomains — this is a multi-tenant app where
spheres live on subdomains, and the login flow legitimately bounces users
back to the subdomain they came from).

## Current state

All in `src/ludamus/adapters/web/django/views.py`.

`Auth0LoginActionView` (the helper that builds the redirect to Auth0),
`views.py:134-161` — `next_path` is taken from GET unvalidated; when the user
arrives on a sphere subdomain it is absolutized against that subdomain and
forwarded to the root-domain login URL; it is then stored in cache as OAuth
state:

```python
root_domain = request.di.uow.spheres.read_site(
    request.context.root_sphere_id
).domain
next_path = request.GET.get("next")
if request.get_host() != root_domain:
    if next_path:
        next_path = request.build_absolute_uri(next_path)
    ...
state_data = {
    "redirect_to": next_path,
    "created_at": datetime.now(UTC).isoformat(),
    "csrf_token": request.META.get("CSRF_COOKIE", ""),
}
cache.set(cache_key, json.dumps(state_data), timeout=CACHE_TIMEOUT)
```

`Auth0LoginCallbackActionView.get_redirect_url`, `views.py:224-253` — the
stored value comes back as `redirect_to` and is returned directly as the
redirect target (lines 232, 253), or has its scheme+netloc reused (247-250):

```python
if (redirect_to := self._resolve_oauth_state(default_redirect)) is None:
    return index_url
if self.request.context.current_user_slug:
    return redirect_to or index_url
...
if redirect_to:
    parsed = urlparse(redirect_to)
    return (
        f'{parsed.scheme}://{parsed.netloc}{reverse("web:crowd:profile")}'
    )
...
return redirect_to or index_url
```

`_resolve_oauth_state` (`views.py:255-287`) validates only presence, age, and
JSON shape of the state — not the redirect host. Note it ends with
`except KeyError, ValueError:` — this is **valid Python 3.14 syntax (PEP 758)**
meaning "either exception"; do not "fix" it.

Existing tests: `tests/integration/web/crowd/test_auth0_login_callback_action.py`
covers the callback (use it as the structural pattern). View tests use the
`assert_response` utility — see that file and `docs/agents/testing-assertions.md`.

Multi-tenancy facts needed for the allowlist: the root site domain comes from
`request.di.uow.spheres.read_site(request.context.root_sphere_id).domain`;
sphere sites live on subdomains of it (e.g. `kapitularz.<root>`). So a safe
target is: a relative URL, or an absolute URL whose host equals the root
domain **or ends with `"." + root_domain`**, with scheme `http`/`https`.

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| All tests | `mise run test` | all pass |
| Callback tests only | `poetry run pytest tests/integration/web/crowd/test_auth0_login_callback_action.py -x -q` | all pass |
| Lint+format | `mise run check` | exit 0 |
| CI-style lint | `mise run prcheck` | exit 0 |

## Scope

**In scope**:

- `src/ludamus/adapters/web/django/views.py` — `Auth0LoginActionView` /
  `Auth0LoginCallbackActionView` / `_resolve_oauth_state` only
- `tests/integration/web/crowd/test_auth0_login_callback_action.py` (extend)
- A login-action test file alongside it if one exists (extend); if none exists,
  add the login-side cases to the callback test file.

**Out of scope**:

- Storing the CSRF cookie in cache state (separate, low-severity observation).
- Rate limiting (tracked as issue #304).
- Session cookie lifetime settings.
- Any `request.di.uow` → `request.services` migration.

## Git workflow

- Branch: `advisor/002-oauth-next-redirect-validation`
- Commit style: imperative, matching `git log` (e.g. "Reject off-site next
  targets in auth0 login flow").
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add a safety helper

In `views.py`, near the login views, add a module-level helper:

```python
from django.utils.http import url_has_allowed_host_and_scheme

def _is_safe_login_redirect(url: str, root_domain: str) -> bool:
    host = urlparse(url).netloc
    allowed = {root_domain}
    if host and (host == root_domain or host.endswith(f".{root_domain}")):
        allowed.add(host)
    return url_has_allowed_host_and_scheme(
        url, allowed_hosts=allowed, require_https=not settings.DEBUG
    )
```

Adjust the `require_https` expression to whatever the module already uses to
distinguish dev/prod (check how `settings` is imported/used in this file; if
there is no clean signal, use `require_https=False` and note it — scheme
spoofing still requires a same-domain host).

**Verify**: `mise run prcheck` → exit 0 (mypy strict + ruff pass on the helper).

### Step 2: Validate at both ends

- In `Auth0LoginActionView` (~line 137): after computing `next_path` (and after
  the absolutization branch), drop unsafe values:

  ```python
  if next_path and not _is_safe_login_redirect(next_path, root_domain):
      next_path = None
  ```

  Apply this to the value that gets stored in `state_data["redirect_to"]` AND
  to the value forwarded in the cross-subdomain `?next=` hop (line 144-148) —
  both currently carry the raw value.

- In `Auth0LoginCallbackActionView.get_redirect_url`: defense in depth — after
  `redirect_to` is resolved (~line 228), treat unsafe values as absent:

  ```python
  if redirect_to and not _is_safe_login_redirect(redirect_to, root_domain):
      redirect_to = None
  ```

  The root domain is available the same way as in the login view
  (`self.request.di.uow.spheres.read_site(self.request.context.root_sphere_id).domain`).
  This also neutralizes the scheme/netloc-reuse at lines 247-250.

**Verify**: `poetry run pytest tests/integration/web/crowd/ -x -q` → all
existing tests pass (legitimate relative and subdomain redirects unaffected).

### Step 3: Tests

Add to `tests/integration/web/crowd/test_auth0_login_callback_action.py`
(model setup on the existing tests there — they already fake the OAuth state
cache entry and the Auth0 token exchange):

1. `next=https://evil.example/` in state → callback redirects to index, not evil.
2. `next=//evil.example/` (protocol-relative) → index.
3. `next=/event/foo/` (relative) → still honored (regression guard).
4. Absolute URL on a sphere subdomain of the root domain → still honored.
5. Login view: `GET /crowd/auth0/login?next=https://evil.example/` → the cached
   state's `redirect_to` is `None` (or the test asserts the eventual redirect
   is index after the callback round-trip, whichever the existing tests make easy).

**Verify**: `poetry run pytest tests/integration/web/crowd/ -x -q` → all pass,
including 5 new tests.

### Step 4: Full gate

**Verify**: `mise run test` → all pass; `mise run prcheck` → exit 0.

## Done criteria

- [ ] `grep -n "url_has_allowed_host_and_scheme"
  src/ludamus/adapters/web/django/views.py` matches
- [ ] New tests for external/protocol-relative/relative/subdomain `next` exist
  and pass
- [ ] `mise run test` exits 0; `mise run prcheck` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Existing callback tests rely on redirecting to an arbitrary absolute URL
  (would indicate an intended cross-site flow this plan would break).
- The sphere/site model gives more than one root domain (the helper assumes
  one root domain per deployment) — report how multi-root should be handled.
- mypy strict rejects the helper signature in a way you can't fix without a
  type-ignore comment (repo forbids those without approval).

## Maintenance notes

- Reviewers should scrutinize the subdomain allowlist rule (`endswith("." +
  root_domain)`) — it intentionally allows *any* subdomain of the root, which
  matches how spheres work today.
- If a future deployment serves multiple root domains, `_is_safe_login_redirect`
  needs the full set.
- Deferred: stop storing `CSRF_COOKIE` in the cached OAuth state (it isn't
  needed for the redirect and widens the blast radius of a cache leak).
