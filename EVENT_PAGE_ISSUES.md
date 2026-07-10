# Event page issues

- [x] In the ledger, there should be no view transition (it's garish to animate
      the ledger row into the full modal). → ledger row carries `data-no-morph`;
      `modal.ts` skips the morph for it.
- [x] Rooms view collapses with real data (kapitularz: ~20 rooms/day): `w-full
      table-fixed` crushes columns to ~50px, tiles overlap. → table min-width
      scales with room count (~10rem/room), horizontal scroll, sticky hour
      column.
- [x] Mobile: hour scrubber doesn't scroll on a real phone. → removed
      `scroll-snap-type: y proximity` from `#app-scroll` (iOS Safari won't run
      programmatic smooth `scrollIntoView` inside a snap container). NEEDS
      CONFIRMATION ON A REAL PHONE.
- [x] Mobile: ledger row meta cluster overflowed. → meta wraps to its own line
      on mobile; time stacks as {start}\n{end} in a narrower column.
- [x] Mobile: compact schedule spans full width — `-mx-4` counters `main`'s
      `px-4`; day sheets drop side borders/rounding below `sm`.
- [x] Scrubber: `overscroll-behavior: none`, wheel over the rail scrolls the
      schedule, drag already worked.
- [x] Ledger: drop the "N participants" counter — availability ("N spots
      left") is the same information; row is `items-center`.
- [x] Rename `.session-card` → `.session` (`-wrapper`, `-link`, `-suppressed`
      follow suit). `session-card.ts` file and vite entry name kept.
- [x] The number of bookmarks should be visible so players are able to see
      what's popular and what's not. → count inside the bookmark toggle,
      read-only badge for anonymous visitors, live ±1 on toggle.
- [x] The hover bg on ledger row should not be visible when the bookmark
      button is hovered. Also ensure we have legal nesting (use absolute
      anchor pattern). → `has-[a:hover]:bg-bg-tertiary` scopes the hover to
      the stretched link; verified 0 nested interactive elements across all
      110 rows.

Seed note: a convention-scale fixture already exists —
`tests/e2e/scripts/kapitularz_print_seed.py` (110 sessions, 26 rooms, event
slug `kapitularz-2025-anonymized`), seeded by `mise run test:e2e:prep`. For
the dev DB it was seeded manually this session (event lives in the
`ludamus.localhost:1355` sphere).
