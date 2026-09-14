# 9. Unknown classes (every `class` token means something)

**Status:** 🟢 active — six PRs fanned out, one per bucket below.

An audit ran a Tailwind-aware linter (`@shadcn/lint`, via a throwaway shim that
rewrote every `class="…"` in `src/ludamus/templates` into a `cn("…")` call)
over the whole template tree. Its `no-unknown-classes` rule reports tokens that
Tailwind cannot generate and that no client stylesheet declares. The linter is
not being adopted — it cannot read HTML, and ast-grep covers the checks we
want — but the finding list is a good map of class tokens that have drifted
away from the design system.

Three things hide behind an unknown class, and each gets a different cure:

1. **Styled in a template `<style>` block.** Tailwind and the client build
   never see it, so it cannot use theme tokens, variants, or dark mode the
   normal way. Cure: move the rules into `src/ludamus/client/src/*.css`
   (`@utility` for single-purpose classes, `@layer components` for grouped
   component rules) and delete the block.
2. **A JavaScript or test hook with no styling.** The class is doing an
   attribute's job. Cure: a `data-*` attribute, so `class` carries only look
   and a selector rename can never break styling.
3. **Declared nowhere.** Either the author meant a variant that never got CSS
   (`btn-tertiary`, `icon-btn-danger`) or the token is dead. Cure: add the
   variant to the design system if the uses want it, otherwise delete.

Raw palette colours (`bg-amber-50`, `text-blue-600`, …) came out of the same
audit and are a separate, smaller question: the panel stat tiles use a
category palette on purpose, and the amber warning blocks map onto the
`warning` token. Not part of this refactor.

## Buckets and branches

| Bucket | Cure | Branch |
| ------ | ---- | ------ |
| `chronology/event.html`, `_room_lanes.html`, `print.html` `<style>` blocks (filter sheet, print pointer, room lanes, timetable grid, `session-link`) | 1 | `claude/unknown-classes-chronology-styles` |
| `panel/base.html` sidebar `<style>` block, `sidebar-*` classes, `panel-main` | 1 (+2 for hook-only classes) | `claude/unknown-classes-panel-sidebar` |
| `btn-tertiary`, `icon-btn-danger`, `icon-btn-primary`, and tokens with no CSS anywhere (`form-control`, `cancel-link`, `item-*`, `theme-switcher`, …) | 3 | `claude/unknown-classes-dead-variants` |
| `panel/parts/import-recipe-row.html` + `import-recipe.ts` hooks (`recipe-*`, `ts-*`, `ent-*`, `ov-*`) | 2 | `claude/unknown-classes-import-recipe-hooks` |
| `panel/cfp-edit.html` inline scripts, columns chooser, space tree, facilitator picker, bulk action button hooks | 2 | `claude/unknown-classes-panel-editor-hooks` |
| `notice_board/detail.html` inline script (calendar, share, RSVP menus) and chronology hooks (`session-wrapper`, `bookmark-*`, `waiting-*`) | 2 | `claude/unknown-classes-notice-board-hooks` |

Anchors that Python or tests grep for (`tab-shell`, `tab-nav`, `sidebar-cat`,
`session-tags-cloud`, `bookmark-toggle`, …) stay until every reader moves in
the same PR; a rename that leaves a test pointing at the old token is worse
than the unknown class.

## Re-running the audit

The shim is not checked in. To reproduce: for each template, blank Django
tags to spaces, emit one `cn("<classes>")` per `class` attribute at the same
line and column into a `.ts` file, and run oxlint 1.80+ with `@shadcn/lint`
and only `shadcn/no-unknown-classes` enabled from a directory where
`tailwindcss` resolves and `index.css` is reachable. Line numbers in the report
then match the template.

## Still open

Once the six branches land: decide whether `session-grid`,
`time-slot-section`, and `room-lanes-time` (plain `.class` rules in the client
CSS that the audit still flagged because they sit inside nested selectors)
should become `@utility` declarations. Low value; only worth it if the tiles
get restyled anyway.
