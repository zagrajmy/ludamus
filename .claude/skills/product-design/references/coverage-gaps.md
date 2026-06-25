# Coverage gaps — decisions we have NOT made yet

The honest counterpart to the rest of this skill. These are areas where the
codebase has no canonical decision, so an agent should **flag the gap and make
the smallest reasonable choice**, not invent a standard and present it as house
style.

Per the Decision hierarchy, anything not covered by user goals, system behavior,
canonical guidance (tessera/lint/CLAUDE.md), recorded decisions, or an adjacent
shipped pattern lands here.

## Current gaps

- **Loading / pending UI.** Most views are server-rendered, so there's no
  established skeleton/spinner pattern. As htmx adoption grows
  (`docs/refactors/htmx-adoption.md`), we'll need one. Until then: keep partials
  fast and avoid layout shift; don't introduce a bespoke spinner per page.
- **Toast / transient notifications.** Django `messages` render as alerts on the
  next page. There's no in-page toast convention. Don't add a one-off.
- **Motion / animation.** No catalog of approved transitions. The
  `review-animations` skill and `emil-design-eng` skill hold the craft bar;
  default to little-to-no motion on frequently-seen elements.
- **Dense data / pagination.** `tessera_table` covers a single scrollable table.
  Pagination, column sorting, and bulk-select are undecided. Don't ship a custom
  pager without raising it.
- **Mobile navigation.** The compact-viewport nav pattern isn't documented.
  Check `base.html` and adjacent pages before inventing.
- **Form layout at scale.** `tessera_form` handles short forms well; long,
  multi-section forms (the proposal wizard aside) have no agreed sectioning
  pattern.
- **Date/time presentation.** There's a `date_tags` library; the rules for
  relative vs absolute, timezone display, and range formatting aren't written
  down. Match the nearest existing usage.

## How to use this file

If you make a call in one of these areas, leave a breadcrumb: note what you did
and why in the PR, and — if it's becoming a pattern — propose promoting it to
`patterns.md` or a lint rule. If you hit a gap not listed here, add it. The list
shrinking over time is the point.
