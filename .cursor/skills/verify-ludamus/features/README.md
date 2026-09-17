# Ludamus verification map

Recipes for driving the live UI. Read this index, then the matching feature
file.

Nouns, views, and DTOs are in `docs/agents/architecture.md`. That is not a
drive recipe.

## Baseline preconditions

- A healthy instance: `mise run control-ludamus -- doctor` prints `"ok": true`
  and a `base_url`. Default `mise run start` is portless on `:1355`.
  `Site.domain` is the origin. `--no-portless` is `http://localhost:8000`.
  Doctor also lists `sites`. Public event pages use the sphere host (for
  example `http://polcon26.localhost:8000`), which may not be SITE_ID Local
  root.
- Seed: `mise run bootstrap` for `autumn-open`, `enroll-states`,
  `sunhaven-festival`. `mise run mcp-token` writes an organizer token for
  every event. Doctor's `organizer_events` lists them. A POLCON import will
  not have the demo slugs. Unpublished events 302 to `/events/`. MCP
  `list_events` shows `is_published`.
- MCP tokens in `.local/mcp-tokens.json` (`mise run mcp-token`) if you need
  to inspect programme data. Not required for anonymous UI.
- Never drive a stale portless proxy (`X-Portless: 1` and a 404). Never drive
  the e2e sqlite unless doctor says that is the DB.
- Run doctor again after anything unexpected.

## Driving conventions

- Start every recipe from the baseline unless its preconditions say otherwise.
- Prefer ARIA roles and accessible names. Session cards are named
  `Open details for <title>`.
- Treat every command as literal.
- Browser actions go through `control-ludamus` / `agent-browser`.
- Restore mutated seed (give back a seat, unassign a session). Keep proof
  artifacts.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final screen.
- UI proof includes an ARIA snapshot and a screenshot with the event name
  visible.
- Mutation proof includes a second read-only view of the stored value.
- MCP `list_*` / `get_*` may corroborate a side effect. MCP writes are not
  the action under proof.
- Report an unreachable path with the attempted command and the unmet
  precondition (auth, missing seed event, entitlement).

## Feature entry contract

Each feature file starts with an H1 and one paragraph of user-visible
behavior, then exactly four H2s: `Sub-features`, `How to get to it (user POV)`,
`Driving it with control-ludamus`, `Gotchas`.

## Features

- [Public event and schedule](./public-event.md). Visitor lands on an event,
  switches list/rooms, opens a session.
- [Enrollment](./enrollment.md). Take a seat or join a waiting list from the
  session dialog.
- [Organizer timetable](./panel-timetable.md). Place a session on the grid.
- [Proposal wizard](./propose-session.md). Facilitator submits a session.
