---
name: verify-ludamus
description: >-
  Prove a ludamus (Zagrajmy) web UI change in a real browser. Launches a
  disposable, seeded Django instance on its own port and sqlite file, drives
  it with agent-browser as a visitor or a seeded persona, and saves ARIA
  snapshots and screenshots as evidence. Use after changing a page, form,
  dialog or panel view, or to reproduce a UI report. Entry point:
  `mise run control-ludamus -- launch`.
---

# Verify ludamus

Ludamus is a Django app: server-rendered pages, htmx, a Vite client. People
use the public event pages, enrollment, the proposal wizard and the organizer
panel. This skill drives those pages. Django admin, print pages and the MCP
API are out of scope as the action under proof. Read
[features/README.md](features/README.md), then the feature file you need.

Every command below is `mise run control-ludamus -- <command>`
(`scripts/control_ludamus.py`). It prints JSON or agent-browser output and
exits non-zero when a step fails.

## Launch

```bash
mise run control-ludamus -- launch
```

Takes about 40 seconds. From an empty data dir it:

1. makes `.local/verify-ludamus/runs/<run-id>/` and picks a free port;
2. runs `migrate`, `createcachetable`, `downloadvendor` and the seed scripts
   (`bootstrap_data`, `bootstrap_facilitators`, `bootstrap_timetable`,
   `bootstrap_large_event` with 40 sessions) against that run's
   `db.sqlite3`;
3. moves the seeded sphere hosts from `:8000` to the run's port;
4. mints MCP tokens into the run dir and builds the Vite client;
5. starts `runserver --noreload` on `localhost:<port>` in its own process
   group, with `.env.e2e` settings (ENV=test, built assets, enforcing CSP);
6. waits until `/healthz/` is ok, `/` and `/event/autumn-open/` answer 200,
   and the page's stylesheet is served.

It prints the run record (`base_url`, `pid`, `db`, `evidence_dir`). The same
record lives in `.local/verify-ludamus/current.json`. If an instance is
already running, launch prints it and starts nothing.

The instance does not reload code. After you edit code, run cleanup and
launch again. Doctor reports `"fresh": false` when the source has changed
since launch.

It never touches the dev DB (`ludamus.sqlite3`), the e2e DB, port 8000, or
`tests/e2e/.auth-state*.json`. It runs beside `mise run start` and an e2e
run.

## Doctor

```bash
mise run control-ludamus -- doctor
```

Read-only. Run it first, and again whenever something looks wrong. Exit 0 and
`"ok": true` mean all of these hold: the recorded pid is alive, it owns the
port, `/healthz/` is ok, the ready pages answer, and the stylesheet is
served. It also prints `fresh`, `persona`, the persona names, and `sites`
(one origin per sphere host). `advice` says what to do when a check fails.

## Drive

agent-browser runs in a session named `verify-ludamus-<run-id>`, so it never
reuses your other browser sessions. Paths join onto `base_url`. Pass a full
URL for other sphere hosts from doctor's `sites`.

```bash
mise run control-ludamus -- open /event/autumn-open/
mise run control-ludamus -- find role link click --name "View the program"
mise run control-ludamus -- press link "Open details for Mega Strategy Lab" Enter
mise run control-ludamus -- find role button click --name Enroll
mise run control-ludamus -- browser get url
```

- `find <locator> <value> [click|fill|check|hover|text] --name <name>` acts
  by ARIA role and accessible name. Use it before anything else.
- `press <role> <name> <key>` focuses by role and name, then presses a key.
  Use it where a click lands on a covering element, such as the stretched
  session-card links (the e2e specs press `Enter` on them too).
- `browser <agent-browser args>` passes through (`get url`, `wait`, `eval`,
  `errors`, `console`). Do not drive with CSS selectors or coordinates.

### Personas

Seeding signs users in and stores their session cookies in the run's
`personas/` folder. `persona <name>` closes the browser session and loads
that user's cookies. `persona anonymous` signs out.

```bash
mise run control-ludamus -- persona e2e-tester
```

| Persona | Who |
| --- | --- |
| `anonymous` | Visitor. Root `/` shows the landing page, not events. |
| `e2e-tester` | Attendee on the root sphere. `/` is the dashboard with event cards. |
| `superuser` | `admin`, a superuser. |
| `crew-manager` | Manages the `crew.localhost` sphere. |
| `waiter`, `notified`, `profile`, `party-*`, `invitee`, `discord`, `empty` | Single-scenario users from `bootstrap_data.py`. |

For the organizer panel, sign in through `/admin/login/` as `e2e-manager` /
`e2e-manager-123`. That user manages the root sphere. See
[features/panel-timetable.md](features/panel-timetable.md). The Auth0 login
does not work here: `.env.e2e` points at a fake tenant.

### Read-only programme checks

```bash
mise run control-ludamus -- mcp --event autumn-open list_sessions
mise run control-ludamus -- mcp --scope maintainer list_spheres
```

MCP uses the run's own tokens. It can confirm a side effect. It is not the
action under proof.

## Evidence

`snapshot <path>` and `screenshot <path>` write under the run's
`evidence_dir`, `.local/verify-ludamus/evidence/<run-id>/` (gitignored).
Name files `<feature-id>/<step>.<ext>`.

```bash
mise run control-ludamus -- snapshot public-event/session-dialog.snapshot.txt
mise run control-ludamus -- screenshot public-event/session-dialog.png
```

`screenshot` captures the full page. It first unpins `#app-scroll`, which
otherwise clips the capture to one viewport.

Proof standards:

- Drive the path a user takes. A test-only endpoint, an MCP write or an ORM
  call is not the action under proof.
- Capture the action and the state it produced: a snapshot before, a
  snapshot and a screenshot after.
- For a mutation, check a second view: reload the page, reopen the dialog,
  or read the value back with MCP `list_*` / `get_*`.
- Outgoing mail goes to files in the run's `mail/` folder. Copy any message
  you rely on into the evidence dir before cleanup.
- Name the persona, the feature id and the entry point with every artifact.
- Mock nothing. The e2e settings already isolate Auth0, payments and
  PostHog.

## Cleanup

```bash
mise run control-ludamus -- cleanup
```

Sends SIGTERM (SIGKILL after 10 s) to the instance's own process group, then
closes its browser session. It copies `launch.log` and `server.log` into the
evidence dir, deletes the run dir and clears `current.json`. Evidence stays.
Run it after every attempt, failed ones included. A failed launch leaves its
logs in the run dir, and cleanup collects them.

Never use `mise run kill`, `mise run test:e2e:kill`, `pkill` or `lsof | kill`
here. Those kill by port or process name and take down the user's servers.

## Helpers

| Command | Does |
| --- | --- |
| `launch` | Seed and start a disposable instance. |
| `doctor` | Is the instance worth driving? |
| `persona <name>` | Switch the signed-in user (`anonymous` signs out). |
| `open <path or URL>` | Navigate. |
| `find <locator> <value> [action] --name <name>` | Act by ARIA role and name. |
| `press <role> <name> <key>` | Focus by role and name, press a key. |
| `snapshot <path>` | ARIA snapshot into the evidence dir. |
| `screenshot <path>` | Full-page PNG into the evidence dir. |
| `browser <args>` | Pass through to agent-browser. |
| `mcp [--scope maintainer] [--event <slug>] <tool> [json]` | Read-only MCP call. |
| `cleanup` | Stop the instance. Evidence stays. |

When the app changes, refresh the feature map with
`/maintain-verification-skill`.
