# Organizer timetable

The timetable is where an organizer places an accepted session onto a room and
a time. Mutations stay on `sunhaven-festival` so they do not show up on the
public `autumn-open` page.

## Sub-features

- `timetable-open` opens the event schedule grid in the panel.
- `timetable-browse` lists unscheduled sessions in the side pane.
- `timetable-assign` places a session on the grid.
- `timetable-unassign` takes it back off.

## How to get to it (user POV)

- Sign in as a sphere manager, open `/panel/event/sunhaven-festival/timetable/`.
- Staff sign in at `/admin/login/` as `e2e-manager` / `e2e-manager-123`
  (manages the root sphere), then open the same path.

## Driving it with control-ludamus

Preconditions:

- Seed includes `sunhaven-festival` (launch runs `bootstrap_timetable.py`).
- You are a manager of that event's sphere. Doctor MCP `--event sunhaven-festival`
  `get_current_event` is a useful pre-check, not the proof.
- Restore any assignment you make.

- **Sign in.** Open `/admin/login/`, fill username `e2e-manager` and
  password `e2e-manager-123`, submit. The admin index loads. Auth0 login
  does not work on the launched instance (fake tenant in `.env.e2e`), so
  admin login is the staff path, as in the panel e2e specs.
- **Open the grid.** Run
  `mise run control-ludamus -- open /panel/event/sunhaven-festival/timetable/`.
  The heading is `Schedule`. `#timetable-grid` is present. Unscheduled
  sessions are in the browse pane.
- **Place a session.** Choose an unscheduled session, then a cell on the grid
  (assign mode: `Click a position on the grid to place the session`). Escape
  cancels assign mode.
- **Proof.** The session title is on the grid. Snapshot and screenshot. A
  read-only check:
  `mise run control-ludamus -- mcp --event sunhaven-festival list_sessions`.
  Then unassign so the next run sees the seeded unscheduled list.

## Gotchas

- Do not schedule onto `autumn-open`. That page is the public-event fixture.
- Panel access means you manage this sphere. A foreign event slug 404s even
  if the pk exists.
- MCP `assign_session` will place the session. That is seed, not this proof.
- Filter controls (`Track`, rooms, facilitators) narrow the grid. They are
  not the assign action.
