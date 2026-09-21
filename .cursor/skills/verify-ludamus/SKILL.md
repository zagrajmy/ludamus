---
name: verify-ludamus
description: >-
  Drive the ludamus web UI with agent-browser. Save screenshots and
  accessibility snapshots. Use when checking a UI change or reproducing a
  report. Launch with `mise run control-ludamus`. MCP can seed or inspect
  programme data. That is not UI proof.
---

# Verify ludamus

Zagrajmy/ludamus is a Django web app: server-rendered pages, htmx, a Vite
client. People use the public event, schedule, and enrollment pages, and the
organizer panel. Maintainer/organizer MCP, Django admin, and print pages are
out of scope here. This skill is the web UI. Read
[features/README.md](features/README.md) before driving.

## Launch

Attach to a running instance. Default `mise run start` is portless:
`http://<name>.localhost:1355`, also stored on `Site.domain`. Django still
binds an app port behind that proxy. `mise run start -- --no-portless` is
`http://localhost:8000`.

```bash
mise run control-ludamus -- launch
```

Launch attaches when `GET {origin}/healthz/` is ok. If Site.domain is not
healthy, it does not start another server and it does not invent a
`base_url` from `:8000` or `:1355`. Portless `:1355` is one listen port for
every worktree. Run `mise run start` yourself, then launch again.

Ready means `GET {base}/healthz/` returns `{"status":"ok"}`. Doctor prints
`base_url` equal to Site.domain. `mise run start` also runs Vite. A bare
`runserver` serves HTML without CSS.

Do not run `mise run kill`, `mise run test:e2e:kill`, or `pkill portless`.
Those match by port or process name and will take the user's session. A
portless proxy that returns 404 with `X-Portless: 1` is stale. It is not the
app.

## Doctor

```bash
mise run control-ludamus -- doctor
```

Read-only. It reports whether `/healthz/` answers, which origin, which DB,
whether `.local/mcp-tokens.json` exists, whether MCP `ping` works, and
whether `:1355` is a stale proxy. Run it first when anything looks off.
Exit 1 means do not drive.

Mint tokens with `mise run mcp-token` (also the last step of
`mise run bootstrap`). Remint after `SECRET_KEY` changes. Tokens are for MCP
seed and inspect, not for logging into the UI.

## Drive

`control-ludamus` calls `aubx agent-browser`. Click by ARIA role and name, or
by route. Do not use CSS selectors or coordinates. Prefer `find` (it owns
`--name`) over `browser -- find`.

```bash
mise run control-ludamus -- open /event/autumn-open/
mise run control-ludamus -- snapshot public-event.snapshot.txt
mise run control-ludamus -- find role link click --name "View the program"
mise run control-ludamus -- screenshot public-event.png
```

`open` joins a path onto doctor's `base_url` (SITE_ID). Sphere events often
live on another Site. Doctor lists `sites`. Pass that origin as an absolute
URL when it differs.

Personas:

| Who | How |
| --- | --- |
| Anonymous visitor | just `open` |
| Attendee | Playwright `tests/e2e/.auth-state.json` (`e2e-tester`) after `mise run test:e2e:prep`. That is a different DB than `mise start`. |
| Sphere manager (Auth0 simulator) | `default@example.com` / `12345` |
| Staff panel | `/admin/login/` as `admin` / `admin` or `e2e-manager` / `e2e-manager-123` |

Do not mix the e2e sqlite (`dev.e2e.sqlite3` on `:8000` after prep) with the
dev DB. Doctor's `db` field is the check.

MCP can list or create programme rows:

```bash
mise run control-ludamus -- mcp --scope maintainer list_spheres
mise run control-ludamus -- mcp --event autumn-open list_sessions
```

Creating a session through MCP does not prove the proposal wizard.

## Evidence

Put files in `.local/verify-ludamus/evidence/` (gitignored). Cleanup leaves
them in place.

- Drive the live page the way a user would. Do not use a test-only endpoint,
  an MCP write, or the ORM as the action under proof.
- Save the action and the resulting state (snapshot and screenshot).
- For a mutation, confirm a second user-facing view: reopen the session,
  reload the list, or a read-only MCP `get_*` / `list_*`.
- Record the feature id and entry point with every artifact.
- Auth0 simulator and Stripe/ticket APIs are already isolated in local env.
  Do not mock the app.

## Cleanup

```bash
mise run control-ludamus -- cleanup
```

No-op. This skill never starts a server, so it never kills one. Evidence
stays. Never kill by process name or by `:8000` / `:1355`.

## Helpers

```bash
mise run control-ludamus -- doctor
mise run control-ludamus -- launch
mise run control-ludamus -- open /event/autumn-open/
mise run control-ludamus -- snapshot public-event.snapshot.txt
mise run control-ludamus -- screenshot public-event.png
mise run control-ludamus -- find role link click --name "View the program"
mise run control-ludamus -- mcp --event autumn-open list_spaces
mise run control-ludamus -- cleanup
mise run mcp-token
```

When the app changes, update the feature map with
`/maintain-verification-skill`.
