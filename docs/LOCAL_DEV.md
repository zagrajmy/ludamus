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

The seeded sphere-manager login is:

```text
Email: default@example.com
Password: 12345
```

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

## Toolchain glossary

The task files (`mise.toml`, `tasks.toml`) lean on a few tools that are easy
to mistake for typos:

- **mise** — tool-version manager and task runner. `mise.toml` pins the
  toolchain (Python, Node, Poetry, hk, …) and holds most tasks; `tasks.toml`
  adds the Django-facing ones. `mise tasks` lists everything.
- **aube / aubr / aubx** — the `@endevco/aube` JS workspace tool, installed
  through mise. `aube install` installs JS deps for the packages listed in
  `aube-workspace.yaml` (the Vite client and the e2e suite; `paranoid: true`
  blocks package build scripts unless allowlisted under `allowBuilds`).
  `aubr` runs `package.json` scripts (`aubr -C src/ludamus/client build`);
  `aubx` executes installed binaries (`aubx agent-browser` powers
  `mise run shots`).
- **varlock** — env loader/validator, a root `package.json` dependency
  wrapped by the root `varlock` script (`varlock run --`). It validates the
  environment against `.env.schema` (decorators such as `@sensitive` and
  `@required=forEnv(production)`) before running the wrapped command; nearly
  every Django task goes through `aubr varlock django-admin …`.
- **hk** — git-hook and linter runner, pinned in `mise.toml` and configured
  in `hk.pkl` (Pkl). `mise run lint:hk` runs `hk check --all`;
  `mise run bootstrap` wires the hooks with `hk install --mise`.
