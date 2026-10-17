# Ludamus verification map

These are the recipes for driving the live UI. Read this index, then the
feature file that matches your change.

The codebase map (nouns, views, DTOs) is `docs/agents/architecture.md`. It is
not a drive recipe.

## Baseline preconditions

- `mise run control-ludamus -- launch` has run, and `doctor` exits 0 with
  `"ok": true` and `"fresh": true`.
- The seed is the launch seed: `autumn-open`, `enroll-states`,
  `sunhaven-festival`, `perf-marathon` (40 sessions) and the scenario events
  from `bootstrap_data.py`. All of them sit on the root sphere at
  `base_url`, except the `crew`, `another` and `foreign` sphere hosts that
  doctor lists in `sites`.
- The persona is `anonymous` unless a recipe names one. Switch with
  `persona <name>`.
- Never drive an instance this run did not launch. Doctor's `pid` and port
  owner check cover that.

## Driving conventions

- Start every recipe from the baseline unless its preconditions say
  otherwise.
- Use ARIA roles and accessible names. Session cards are links named
  `Open details for <title>`. Open them with
  `press link "Open details for <title>" Enter`, because a click lands on
  the card text that covers the link.
- Treat every command as literal.
- Run browser actions through `mise run control-ludamus -- …`.
- Undo seed mutations before you finish (give back a seat, unassign a
  session), or launch a fresh instance.
- The UI is English on the seeded root sphere. Sphere locale decides the
  language, so snapshot first and use the names you see.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final
  screen.
- UI proof is an ARIA snapshot plus a screenshot with the event name
  visible.
- Mutation proof includes a second, read-only view of the stored value.
- MCP `list_*` / `get_*` may corroborate a side effect. An MCP write is
  never the action under proof.
- Report an unreachable path with the command you ran and the precondition
  that was missing (persona, seed event, entitlement). Do not report a
  skipped entry point as verified through another path.

## Feature entry contract

Each feature file starts with an H1 and one paragraph of user-visible
behavior, then exactly four H2s: `Sub-features`, `How to get to it (user
POV)`, `Driving it with control-ludamus`, `Gotchas`.

## Features

- [Public event and schedule](./public-event.md): reach an event, jump to
  the programme, switch List/Rooms, open a session. Last driven end to end
  2026-10-14.
- [Enrollment](./enrollment.md): take a seat or join a waiting list from the
  session dialog. Not yet re-driven since launch replaced attach mode.
- [Organizer timetable](./panel-timetable.md): place a session on the grid.
  Not yet re-driven since launch replaced attach mode.
- [Proposal wizard](./propose-session.md): a facilitator submits a session.
  Not yet re-driven since launch replaced attach mode.
