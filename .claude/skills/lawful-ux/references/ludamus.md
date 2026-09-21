# Where the laws bite in ludamus

The canon is general; this file is where it lands in this product. Use it to
find the law that applies to the surface you're editing, and the check that
would catch a regression there. These are the questions to ask of the screen,
not a list of known defects — verify against the current template before
reporting anything.

## Programme and schedule (`templates/chronology/`)

The densest surface in the product: many sessions, several views, filters, and
a time axis.

- **Prägnanz + Uniform Connectedness** — `_room_lanes.html`,
  `_card_schedule.html`, `_compact_schedule.html` all express the same set in
  different shapes. Each shape must stay internally regular; a lane that wraps
  into ragged rows loses the grouping the lanes exist to create. CLAUDE.md's
  "UIs have types" rule is this law: a tag cloud (`session_tags_cloud.html`)
  wraps tokens that carry their own kind; restacking it into ragged rows breaks
  the type.
- **Similarity** — a switcher (`_schedule_view_tabs.html`) switches layouts of
  the same set, a filter narrows the set, a sort reorders it. Three different
  functions must not share one visual treatment, and a filter sitting among the
  view tabs is exactly the similarity error.
- **Serial Position** — in the day/time axis, first and last are remembered;
  the "now" marker (`_schedule_now_marker.html`) exists because the middle of a
  long day otherwise blurs.
- **Common Region** — a session card is a boundary; anything inside it must
  belong to that session. Check `_session_card.html` and
  `_compact_session_row.html` when adding a control: does it act on this
  session, or on the page?
- **Von Restorff** — on a grid of near-identical cards, only availability and
  the user's own state (enrolled, waiting, bookmarked) earn emphasis. Every
  card carrying a colored badge spends the budget to zero.

## Enrolment and seats (`enroll_select.html`, `anonymous_enroll.html`, `_session_seat_count.html`)

The path most users came for. Pareto says this is where the effort goes.

- **Hick's Law** — the seat/companion choice should present what's actually
  choosable and nothing else. tessera already collapses a required field with a
  single option (`render_forced_choice`); don't hand-roll a widget that undoes
  it.
- **Doherty Threshold** — seat state is contended. The click must acknowledge
  within 400 ms even when the write is still in flight, and the button must
  keep its label while it works.
- **Goal-Gradient + Zeigarnik** — a partially finished enrolment (profile data
  missing, companion not chosen) must be visible and resumable from where the
  user returns, not silently dropped.
- **Peak-End** — the peak here is "is there a seat for me", the end is the
  confirmation or the refusal. A refusal must say what happened and what to do
  next (waitlist, another slot); a bare error page is the whole experience for
  that user.
- **Postel's Law** — accept the names, phone numbers, and dates people actually
  type. Normalize; don't reject formatting we can fix.

## Filters and search (`components/multiselect-filter.html`, `session-filters.ts`)

- **Hick's Law** — filter *facets* are choices too. More than a handful of
  top-level facets and the panel becomes the task.
- **Selective Attention** — an active-filter state must be visible in the
  content area, not only inside the filter panel; users who don't see why a
  list is short conclude the event is empty.
- **Zeigarnik + deep links** — filter state belongs in the URL so Back and
  refresh keep the user's place (already the house rule in
  product-design/interface-quality).

## Forms (tessera `form.py`, `input.py`, `form_select.py`)

The renderers are the chokepoint — a law honored here is honored everywhere.

- **Chunking / Miller** — group long forms into named sections; never a section
  called "Other". Format identifiers and codes into groups.
- **Working memory** — a confirmation step must restate the values being
  confirmed; a code sent by email must be pasteable.
- **Tesler's Law** — every field removed from a form has to be absorbed
  somewhere: inferred, defaulted, or asked later. If it becomes a support
  email, the complexity didn't go away.
- **Fitts's Law** — submit is the big target; destructive actions are not
  adjacent to it without separation.

## Organizer panel (`templates/panel/`)

Expert surface, repeated use, high consequence.

- **Jakob's Law** — organizers live in spreadsheets and admin tools. Tables,
  bulk selection, and keyboard behavior should match that world, not invent one.
- **Tesler's Law** — this is where irreducible complexity is *supposed* to
  live. Don't oversimplify the panel and push the work to the participant
  surface.
- **Von Restorff** — status badges (`_proposal_status_badge.html`) are the
  emphasis budget for the panel; ordinary rows stay quiet so exceptions read.
- **Serial Position + Fitts** — the actions used every day belong at the ends
  of a toolbar and at full size, not in the middle at icon scale.
- Panel authz is not a UX law but is non-negotiable here: panel access proves
  you manage the current sphere/event, not the objects the request names
  (CLAUDE.md).

## Icon-only controls everywhere

**Fitts's Law** with a number: the `.icon-btn` glyph is ~14 px, so the button
needs padding to clear 24 px pointer / 44 px touch. **Similarity** requires the
accessible name (`sr-only`) that `rules/icon-btn-accessible-name.yml` enforces
— a control whose meaning is carried by shape alone fails for anyone who
doesn't share the icon's convention.

## Polish copy as a stress test

Polish strings run roughly 15–20% longer than English. That length is what
breaks proximity-only grouping, single-line tabs, and card grids — so
**Uniform Connectedness** ("would this grouping survive a rewrap?") is checked
by looking at the Polish build, not the English one. Terms are fixed by
CLAUDE.md's translation table (`session` → "punkt programu", `track` → "blok",
`time slot` → "przedział czasowy", and the rest); a law never overrides those.

## Verifying a law-based finding

- Option counts, list lengths, target sizes: read them off the rendered page
  (`mise run shots -- <path>`), not off the template.
- Response times: measure the actual request, don't assume.
- Grouping claims: check at a narrow viewport and with a long title, since both
  are where the grouping fails first.
- Anything mechanical and repeatable should end up as an `ast-grep` rule in
  `rules/` rather than as advice — same policy as the product-design skill.
