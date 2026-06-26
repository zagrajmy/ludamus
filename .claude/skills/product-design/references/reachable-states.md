# Reachable states — design the whole screen, not the happy path

A screen is every state the user can land on, not just the one where data exists
and nothing failed. Agent-built UI tends to ship the happy path and default the
rest. Don't.

For any screen you add or materially change, walk this list and design each state
that this change can actually reach. If a state is unreachable here, say so —
don't pad the diff.

## The states

- **Loading.** What shows while data is in flight? (Most ludamus views render
  server-side, so this is often N/A — but htmx-driven partials and slow queries
  are not. Don't leave a blank flash.)
- **Empty.** No items yet. An empty state is a *designed* state: say what would
  go here and give the primary action to create the first one. A bare "No
  results." is a missed opportunity, not an empty state.
- **Error.** The action failed or data couldn't load. Say what happened in plain
  language and what the user can do next. Never a dead end. See copy.md.
- **Validation.** Field-level errors render next to the field
  (`tessera_field`/`tessera_errors` handle this) — don't roll your own error
  placement. The form keeps the user's input.
- **Permission denied.** The user is signed in but not allowed. Distinguish from
  "not signed in" (which redirects to login).
- **Destructive confirm.** Deleting/cancelling something irreversible asks first,
  with a `variant="danger"` action labelled with the specific Verb + Noun
  ("Delete proposal", not "Confirm"). Don't add a confirm step to a reversible,
  low-stakes action — that's torturing the user.
- **Narrow viewport.** The compact layout is a state, not an afterthought. Tables
  scroll (`tessera_table` gives you this); actions stack; nothing overflows.

## Stress the content, not just the states

Before you're done, push the extremes — these are where agent UI breaks:

- **Long content.** A 120-character event title, a 40-item list, a user with no
  display name. Does it wrap, truncate, or explode?
- **Large values.** 9999 participants, a 0 count, a negative or missing number.
- **Constrained width.** The narrowest supported viewport.
- **Slow / failed load.** For anything fetched after first paint.

If you changed a screen and can't say which of these you exercised, you haven't
finished the change — you've finished the demo.
