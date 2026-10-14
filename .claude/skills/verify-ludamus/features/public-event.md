# Public event and schedule

The public event page shows the hero, the programme, and a way into each
session. Big programmes (20 or more scheduled sessions) also offer List and
Rooms, two layouts of the same set.

## Sub-features

- `event-open` reaches the event from the dashboard card or a direct URL.
- `event-hero` shows the programme CTAs `View the program` and
  `Sign up for sessions`.
- `schedule-list` is the list layout of the programme.
- `schedule-rooms` is the rooms layout of the same sessions.
- `session-open` opens a session dialog from a card.

## How to get to it (user POV)

- Signed in: `/` is the dashboard. Choose the event card (seeded name
  `Autumn Open Playtest`).
- Anyone: open `/event/autumn-open/` directly. Anonymous `/` on the root
  sphere is the landing page, and `/events/` redirects there.
- From the hero, choose `View the program` (`#schedule-region`) or
  `Sign up for sessions` (`?enrollment=1#schedule-region`).
- On a big programme, choose the `List` or `Rooms` tab in the tablist named
  `Schedule view` (`?view=rooms`).

## Driving it with control-ludamus

Preconditions:

- Doctor is ok and fresh. Seed has `autumn-open` (3 sessions) and
  `perf-marathon` (40 sessions).
- Persona `e2e-tester` for the dashboard entry. Any persona for the rest.

- **Dashboard entry.** Sign in and choose the card. Run
  `mise run control-ludamus -- persona e2e-tester`,
  `mise run control-ludamus -- open /`, then
  `mise run control-ludamus -- find role link click --name "Autumn Open Playtest"`.
  `browser get url` ends in `/event/autumn-open/`, and the level-1 heading
  reads `Autumn Open Playtest`.
- **Direct entry.** Run
  `mise run control-ludamus -- open /event/autumn-open/`. Links named
  `View the program` and `Sign up for sessions` are present.
- **Jump to the programme.** Run
  `mise run control-ludamus -- find role link click --name "View the program"`.
  The URL gains `#schedule-region`. The heading `Sessions` and the card links
  `Open details for <title>` are in the snapshot.
- **Rooms layout.** Run
  `mise run control-ludamus -- open /event/perf-marathon/`, then
  `mise run control-ludamus -- find role tab click --name Rooms`. The URL
  gains `?view=rooms`, tab `Rooms` is `selected`, and a region named
  `Rooms schedule` holds the same `Open details for <title>` links.
- **Open a session.** On `/event/autumn-open/`, run
  `mise run control-ludamus -- press link "Open details for Mega Strategy Lab" Enter`.
  A dialog named `Mega Strategy Lab` appears with buttons `Close` and
  `Enroll` (when signed in).
- **Proof.** Run
  `mise run control-ludamus -- snapshot public-event/session-dialog.snapshot.txt`
  and `mise run control-ludamus -- screenshot public-event/session-dialog.png`.
  Snapshot the event page before opening the dialog too. Record the persona
  and slug.

## Gotchas

- `find role link click` on a session card fails with "is covered by
  <p.pointer-events-auto…>". Use `press … Enter` (the e2e specs do the
  same).
- `autumn-open` has 3 sessions, below the 20 needed for the List/Rooms
  switcher, so it has no `Schedule view` tablist. Use `perf-marathon` for
  `schedule-rooms`.
- `perf-marathon` titles come from Faker with a fixed seed (for example
  `Enjoy here away`). Read them from the snapshot. Do not hardcode them
  across seed changes.
- Signed-in pages may show an `Email verification` region. It is a banner,
  not an error.
- `List` / `Rooms` is a switcher. Filters (`Filters`, `STATUS`, `DAY`, …)
  live in the programme toolbar and narrow the set.
- Opening a session is not enrollment. See [enrollment.md](./enrollment.md).
