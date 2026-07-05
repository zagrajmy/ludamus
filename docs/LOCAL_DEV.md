# Local development

```bash
poetry install      # in a fresh worktree, populate the mise-managed .venv
mise run start       # dev server on :8000 (Django + client watch)
mise run bootstrap   # seed a local sphere, admin user, and demo event
```

## Logging in locally (auth0-simulator)

Auth0 is the real identity provider, so local login goes through a bundled
**auth0-simulator** instead of the production tenant. It is enabled only when
`AUTH0_DOMAIN` is local-shaped — `localhost`, `*.localhost`, `*.local`, or
`auth0.local*` — and TLS certs exist at `~/.portless` (symlinked into
`~/.simulacrum/certs`). With those in place, `mise run start` runs the simulator
on `:4400` and the normal login flow works against it.

If `AUTH0_DOMAIN` points at a real tenant (the default in some `.env.local`
files), the simulator stays idle and you cannot log in locally — switch
`AUTH0_DOMAIN` to e.g. `auth0.localhost` for simulator-backed login.

## Authenticated browser checks without a UI login (Playwright storageState)

The e2e harness already wires an authenticated session, a seeded database, and
the server — reuse it instead of hand-rolling cookies:

```bash
mise run test:e2e:prep    # migrate + seed + build client; writes tests/e2e/.auth-state.json
```

`tests/e2e/playwright.config.ts` starts the server itself (`webServer`, with
`reuseExistingServer` off CI) and loads `tests/e2e/.auth-state.json`
(`storageState`) — the `e2e-tester` session. Any Playwright script run under
that config (or pointed at the same `storageState`) is logged in with no Auth0
round trip. Seeded logins: `e2e-tester` (member), `e2e-manager` (sphere
manager), `admin`.
