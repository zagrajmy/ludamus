# Enrollment

Enrollment is how a person takes a seat or a waiting place on a session while
the window is open. The session dialog footer is the control. The participants
tab can show the same copy.

## Sub-features

- `enroll-open` opens a session that still has room.
- `enroll-take` takes a seat without a confirm step.
- `enroll-waiting` joins the waiting list when the session is full.
- `enroll-leave` gives the seat or waiting place back.

## How to get to it (user POV)

- On an event, choose `Sign up for sessions`, then a session card
  (`Open details for <title>`).
- Direct: `/event/enroll-states/` (seeded enrollment scenarios).
- Authenticated attendee uses the dialog footer buttons `Enroll`,
  `Join waiting list`, `Cancel`, `Leave`.

## Driving it with control-ludamus

Preconditions:

- Seed includes `enroll-states` with `Seat Available Demo` (room) and
  `Waiting List Only Demo` (full).
- Logged-in attendee. On the e2e DB that is `e2e-tester` via storageState.
  On the bootstrap DB, sign in first. Anonymous enrollment is a different
  entry (`/event/<slug>/session/<id>/enrollment/anonymous`).
- Restore any seat you take before leaving the run.

- **Open a session with room.** Run
  `mise run control-ludamus -- open /event/enroll-states/` then:

  ```bash
  mise run control-ludamus -- find role link click \
    --name "Open details for Seat Available Demo"
  ```

  A dialog named `Seat Available Demo` appears. The footer
  (`[data-session-footer]`) has a button named `Enroll`.
- **Take the seat.** Choose `Enroll`. Run
  `mise run control-ludamus -- find role button click --name Enroll`.
  No confirm dialog. The footer shows `You're enrolled` and a button named
  `Cancel`.
- **Give it back.** Choose `Cancel`. The `Enroll` button returns. A retry
  must see the seeded empty seat, not leftovers.
- **Waiting list.** Open `Waiting List Only Demo`. The footer has
  `Join waiting list` and no `Enroll`. Joining flips to a leave control.
- **Proof.** Snapshot and screenshot of the enrolled footer, then the restored
  empty-seat footer. Optionally corroborate with
  `mise run control-ludamus -- mcp --event enroll-states list_sessions`.
  That is a side-effect check, not the action.

## Gotchas

- Specs that mutate seats run serial because they share a row. Do not enroll
  in two agent sessions against the same row.
- `Cancel` / `Leave` are exact names. Do not click a generic `Confirm`.
- Taking a seat must not ask. A browser `dialog` on enroll is a product bug.
- Closed-window and past-event banners live on other seeded events
  (`closed-enrollment`, `past-convention`). This file is the open window.
- The participants tab can show the same words as the footer. Scope
  assertions to `[data-session-footer]`.
