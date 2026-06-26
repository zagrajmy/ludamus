# Accept-proposal page — design exploration

Three alternative layouts for the "Accept Proposal" page, selectable live via a
`?variant=` query param on the accept URL:

| Variant | URL | Idea |
| --- | --- | --- |
| **A — Focused decision** (default) | `…/accept/` | One column. Proposal is quiet reference up top; the where/when decision is the hero below. |
| **B — Split** | `…/accept/?variant=b` | Proposal stays beside the decision on a sticky pane, so context never scrolls away. The decision card carries the brand gradient accent. |
| **C — Decision first** | `…/accept/?variant=c` | Leads with the only required action; the full proposal waits behind a "View full proposal" disclosure. |

The default (no param) renders Variant A, so existing tests and links are
unaffected. Pick one, then the others (`accept_proposal_b.html`,
`accept_proposal_c.html`) and the `?variant=` switch in
`ProposalAcceptPageView` get deleted.

## Why touch it at all

The previous page stacked two loud cards with generic blue/green headers
("Proposal Details", "Assign to Schedule") that competed for attention and
weren't on brand. It explained a weak affordance with a footnote ("preferred
slots are highlighted in bold") instead of making the obvious choice obvious,
and weighted the destructive escape ("Back to Event") equally with the primary
action in a 50/50 button grid.

All three variants share the same fixes:

- **The decision is the page.** Space + time slot is the one job; the proposal
  is reference. Chrome is removed so the form is what your eye lands on.
- **Preferred times float to the top of the picker** in a "Preferred by the
  facilitator" optgroup — no footnote needed.
- **Brand, not Bootstrap.** Coral primary, teal preferred-slot pills, the
  squircle cards and 3D button from the tessera design system; no ad-hoc
  `bg-info` / `bg-success` headers.
- **One primary action.** "Back to event" is a quiet text link, not a
  half-width button pretending to be equal.

Screenshots in this folder are exploration artifacts: `old-{light,mobile}` (the
page before this change), plus per variant `{a,b,c}-mobile`, `a-{light,dark}`,
`b-{light,dark}`, `c-light`, `c-open`.
