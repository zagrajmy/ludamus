# 8. Dead-end actions (offer it, then refuse it)

**Status:** 🟡 in progress — all but facilitator delete fixed; see Still open.

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

### The five "cannot delete X, it is in use" refusals

Each was a real dependency refused after the click. All five now say so where
the Delete button would be. The reason is visible text, not a `title` on a
disabled button: a disabled button is not focusable, so its tooltip never
reaches the keyboard. Cure 3.

Each list already knew the answer or could get it in one more query; none of
them asks per row, which would have been an N+1:

| List | How the row knows |
| --- | --- |
| Spaces (`panel/_space_tree_node.html`) | `SpaceTreeNodeDTO.undeletable_reason`, folded up the subtree during the walk `list_tree` already does — deleting cascades, so a branch over a scheduled session is undeletable too. No extra query. |
| Time slots (`panel/time-slots.html`) | `TimeSlotRepository.pks_with_proposals`, one query, in the page context. `TimeSlotDTO` is shared with the propose wizard and the accept page, so the set travels beside it rather than on it. |
| Categories (`panel/cfp.html`) | `ProposalCategoriesPageDTO.undeletable_pks` — the page already had its own DTO to put it on. |
| Session fields (`panel/session-fields.html`) | `FieldUsageSummary.is_used`, derived from the usage counts the page already computed. No new query, and no new `request.di.uow` surface, which CLAUDE.md forbids extending. |
| Personal data fields (`panel/personal-data-fields.html`) | The same `FieldUsageSummary.is_used`, against the same refusal in `PersonalDataFieldsService.delete`. |

#### One idiom: the row carries its reason

Every surface answers with the same thing — a sentence for the row, or nothing
when Delete is offered. `SpaceTreeNodeDTO.undeletable_reason` holds it directly,
because that DTO is built in `links`, which may import Django and so `gettext`.

The other four cannot put it on the DTO: `ProposalCategoriesPageDTO` is built
in `mills/proposal_categories.py`, and the personal-data `FieldUsageSummary` in
`mills/submissions/personal_data_fields.py`, and `mills` must not import
Django. But the view may — `gates` already writes Polish everywhere — so each
view turns the fact its service returns into `dict[pk, sentence]`:

```python
context["undeletable_category_reasons"] = {
    pk: _("Has proposals") for pk in page.undeletable_pks
}
```

and every row reads its own reason out of it:

```django
{% include "components/_row_delete_action.html"
   with reason=undeletable_category_reasons|get_item:category.pk
        action_url=... confirm=... csrf_token=csrf_token only %}
```

One include per row, one argument that decides, and `only` so the partial
cannot inherit a stray `reason` from the page. `get_item` returns None for a
row that is missing from the mapping, so the failure direction is "offer
Delete", not a blank cell with neither button nor explanation.

Putting the sentence in the view rather than the template also makes it
assertable: the page tests check `{pk: "Has proposals"}` in the context,
where a set of pks could only ever prove that *something* was flagged.

The partial supplies its own confirmation text when a caller does not: an empty
`data-confirm` makes `confirm.ts` skip the dialog and submit straight away, so
the default keeps the guard on rather than trusting five call sites.

Both field pages share one helper, `field_usage_reasons` in
`panel/views/fields.py`, so that sentence has a single home even though the two
pages build their summaries in different layers.

Spaces is the exception twice over. Its Delete is a row-menu item with icon and
menu styling, not a table-cell action, so it renders its own markup rather than
the shared partial; and its sentence rides on the DTO, sourced from
`SPACE_UNDELETABLE_REASON` in `links/db/django/models.py`. That constant is
delete-affordance copy sitting in the ORM module — unlike its neighbour
`SPACE_NO_CHILDREN_REASON`, which `Space.clean` raises — so moving it to the
gate beside the other four is the tidier end state.

## Still open

- **Facilitator delete** (`panel/facilitators.html`,
  `PanelFacilitatorsService.delete` raising `OrganizerActionRefusal.HAS_SESSIONS`)
  is the last catalogued one. The template already carries a comment choosing
  "always submittable" on race grounds — but that argument justifies keeping the
  refusal, not hiding what the page already knows. The blocker is data, not
  design: the service refuses on `counts.live or counts.deleted`, while
  `FacilitatorListItemDTO.session_count` counts live sessions only, so the row
  cannot answer the real predicate yet.
- **The refusal branches remain** in each view, and should: two organizers can
  act at once, and the row that was deletable when the page rendered may not be
  when the POST lands. That is the race an error message is for.

## Not dead ends (checked, left alone)

- **Bulk actions with an empty selection** (`No proposals selected.`,
  `No facilitators selected.`) — the user selected nothing; there is no state
  we could have shown them. A last-resort server guard, not a dead end.
- **Propose wizard step guards** (`Please select a category first.`) — reached
  only by deep-linking past step one; redirecting to the start is the repair,
  not a refusal. The wizard already collapses a single-category step away.
- **"…not found" redirects** everywhere — the object genuinely isn't there.

## Next step

Give `FacilitatorListItemDTO` a count that matches what the service checks
(live plus soft-deleted), then move that refusal onto the control too.

Also outstanding, found while reviewing this work:

- ~~**One surface of five is covered in `tests/e2e`.**~~ All five are now. The
  Python tests assert the context, which is where CLAUDE.md puts them, so they
  cannot prove a template consumes it: dropping `reason=` from a call site
  leaves the whole Python suite green. Categories are pinned in
  `panel-crud.spec.ts`; session fields, personal data fields, time slots and
  the spaces row menu in `panel.spec.ts`. Each case was checked against a
  deliberately broken template.
- **`SessionRepository.read_event` and `read_time_slots` are now exact
  duplicates** of `EventRepository.read` and `TimeSlotRepository.list_by_event`,
  reached through a join instead of the FK. Adding `event_id` to `SessionDTO`
  would delete both, and turn two `Event` fetches in `mills` into an int
  comparison.
- **`SPACE_UNDELETABLE_REASON` belongs in the gate**, beside the other four
  sentences, rather than in `links/db/django/models.py`.
