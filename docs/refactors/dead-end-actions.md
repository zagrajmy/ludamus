# 8. Dead-end actions (offer it, then refuse it)

**Status:** 🟡 in progress — accept-proposal fixed, the rest catalogued below.

A dead-end action is a control we render, let the user click, and then answer
with an error that only says "go set something else up first". The user paid a
navigation and got nothing. Three cures, in order of preference:

1. **Remove the precondition.** Give the object a sane default so the
   condition can't be false (an event now always owns a space).
2. **Let the action succeed with less.** Drop the optional part rather than the
   whole action — but only where the smaller action is really the same one, not
   a second job smuggled onto the screen.
3. **Don't offer it.** Hide or disable the control, with the reason where the
   control was, when neither of the above applies.

An error message after the click is the fallback for races only — two people
acting on the same object at once — not for state we could see while rendering.

## Fixed

### Accept proposal — blocked on spaces and time slots

`ProposalAcceptPageView` redirected back to the event page with
"No spaces configured for this event. Please create spaces first." (and the
same for time slots) before the page ever rendered. A reviewer reading through
proposals got bounced off the screen over setup they can reach from it.

- `EventsService.create` now creates one default space with the event
  (`SpaceTreeRepository.create_default`), and migration
  `0157_default_space_per_event` backfills events that have none. Cure 1: for
  spaces the condition can no longer be false through the normal data path.
- Time slots can still legitimately be empty — slots can't overlap, so a
  default one spanning the event would collide with every real slot added
  later. So the page renders anyway and says what is missing, with the panel
  link that fixes it. Cure 3, applied to the explanation rather than to a
  control: nothing is offered that would refuse.

The page keeps one job. `accept_session` still means "accept and place", with
both ids required; a reviewer who wants to settle a yes/no before the timetable
exists uses the panel proposal list, where `ProposalStatusService.mark_accepted`
already does exactly that. Splitting that second meaning into this page's form
was considered and dropped: two submits on one card is a fork the reviewer
didn't come to resolve, and it would have given `accept_session` two meanings
selected by whether its arguments were null.

### Copy space to another event — nothing to copy to

`SpaceCopyPageView.get` warned "No other events available to copy to." when the
sphere held a single event. The row menu now hides the item unless a second
event exists (`events|length > 1` in `panel/_space_tree_node.html`). Cure 3.

## Catalogued, not yet fixed

Each is a real dependency — the refusal is correct, the timing is not. They
want cure 3: the list row already knows whether the object is in use, so the
delete control can carry the reason instead of the redirect doing it.

| Where | Message |
| --- | --- |
| `panel/views/venues.py` `SpaceDeleteActionView` | Cannot delete a space with scheduled sessions. |
| `panel/views/time_slots.py` | Cannot delete time slot used in proposals. |
| `panel/views/cfp.py` | Cannot delete category with existing proposals. |
| `panel/views/session_fields.py` | Cannot delete field that is used in categories. |

The blocker is that the list DTOs don't carry a usage count today; adding one
per list is the work. `SpaceTreeNodeDTO.no_children_reason` is the shape to
copy — one field holding both the fact and the sentence that explains it, so
the rule and its wording can't drift apart. Note that space deletion checks the
whole subtree, so the node's own flag is not enough.

## Not dead ends (checked, left alone)

- **Bulk actions with an empty selection** (`No proposals selected.`,
  `No facilitators selected.`) — the user selected nothing; there is no state
  we could have shown them. A last-resort server guard, not a dead end.
- **Propose wizard step guards** (`Please select a category first.`) — reached
  only by deep-linking past step one; redirecting to the start is the repair,
  not a refusal. The wizard already collapses a single-category step away.
- **"…not found" redirects** everywhere — the object genuinely isn't there.

## Next step

Add a usage count to the panel list DTOs for time slots, categories and session
fields, then move those four refusals onto the control.
