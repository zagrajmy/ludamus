# Public event and schedule

The public event page shows the hero, the programme, and a way into a session.
List and rooms are two layouts of the same set.

## Sub-features

- `event-open` opens the event from the home list or a direct URL.
- `event-hero` shows programme CTAs (`View the program`, `Sign up for sessions`).
- `schedule-list` is the list layout of the programme.
- `schedule-rooms` is the rooms layout of the same sessions.
- `session-open` opens a session dialog from a card named `Open details for <title>`.

## How to get to it (user POV)

- Open `/` and choose the event card (seeded name `Autumn Open Playtest`).
- Open `/event/autumn-open/` directly.
- From the hero, choose `View the program` (`#schedule-region`) or
  `Sign up for sessions` (`?enrollment=1#schedule-region`).
- In the schedule region, choose the `Schedule view` tabs `List` or `Rooms`.

## Driving it with control-ludamus

Preconditions:

- Doctor is healthy. Seed includes `autumn-open`, or substitute the slug doctor
  / MCP `list_events` actually reports.
- Anonymous session is enough.

- **Home entry.** Open the index and choose the event. Run
  `mise run control-ludamus -- open /` then
  `mise run control-ludamus -- find role link click --name "Autumn Open Playtest"`.
  The heading reads `Autumn Open Playtest` and the URL matches
  `/event/autumn-open/`.
- **Direct entry.** Run
  `mise run control-ludamus -- open /event/autumn-open/`.
  `[data-event-hero]` is present. Links named `View the program` and
  `Sign up for sessions` are visible.
- **Jump to schedule.** Choose `View the program`. Run
  `mise run control-ludamus -- find role link click --name "View the program"`.
  `#schedule-region` is in view. A tablist named `Schedule view` is present.
- **Rooms layout.** Choose `Rooms`. Run
  `mise run control-ludamus -- find role tab click --name Rooms`.
  A region named `Rooms schedule` appears. Session titles still resolve as
  `Open details for <title>`.
- **Open a session.** Choose a card. Run:

  ```bash
  mise run control-ludamus -- find role link click \
    --name "Open details for Dragons & Dungeons"
  ```

  (substitute a title from the snapshot). A dialog named with that session
  title appears.
- **Proof.** Run
  `mise run control-ludamus -- snapshot public-event.snapshot.txt` and
  `mise run control-ludamus -- screenshot public-event.png`.
  Both show the event name and the schedule. Record the slug used.

## Gotchas

- Home copy and the seeded title must match. A POLCON import has a different
  event name and slug. Doctor first. Do not assume `autumn-open`. Public pages
  live on the sphere `Site.domain` (for example
  `http://polcon26.localhost:8000/event/polcon-2026/`), not on SITE_ID Local
  root. An unpublished event (`is_published: false` via MCP `list_events`)
  302s to `/events/` with "This event is unavailable."
- Locale follows the sphere. This checkout serves Polish: `Zobacz program`,
  not `View the program`. Snapshot the page and use the names you see.
- `List` / `Rooms` are a switcher. Filters live elsewhere.
- Icon-only tabs still have an accessible name (`List`, `Rooms`).
- `#app-scroll` clips viewport screenshots. The `screenshot` command already
  unpins it.
- Opening a session is not enrollment. See [enrollment.md](./enrollment.md).
