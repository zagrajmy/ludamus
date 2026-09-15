# 9. Unknown classes (every `class` token means something)

**Status:** 🟢 active — six PRs fanned out, one per bucket below.

An audit ran a Tailwind-aware linter (`@shadcn/lint`, via a throwaway shim that
rewrote every `class="…"` in `src/ludamus/templates` into a `cn("…")` call)
over the whole template tree. Its `no-unknown-classes` rule reports tokens that
Tailwind cannot generate and that no client stylesheet declares as a top-level
`.class` rule, `@layer components` rule, or `@utility`. It does not see a class
that only appears inside a nested selector (`.timetable .session-grid`), so
such a class is flagged even though its CSS is live; treat every finding as a
lead to verify by grep, never as proof that a token is dead. The linter is not
being adopted — it cannot read HTML, and ast-grep covers the checks we want —
but the finding list is a good map of class tokens that have drifted away from
the design system.

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

Nothing is checked in for this: the linter needs oxlint 1.80+ while the repo
pins 1.70, and adding `@shadcn/lint` as a dependency was rejected because it
cannot read templates. The audit runs from a scratch directory outside the
repo:

```sh
mkdir audit && cd audit
```

Save the two files below into that directory, then run the commands that
follow. Line and column numbers in the report match the template because
each `class` attribute is emitted at its own position.

`.oxlintrc.json`:

```json
{
  "jsPlugins": ["@shadcn/lint"],
  "rules": { "shadcn/no-unknown-classes": "error" }
}
```

`extract.mjs`:

```js
import { readFileSync, writeFileSync, mkdirSync, globSync } from "node:fs";
import { dirname, join } from "node:path";
const [root, out] = process.argv.slice(2);
const blank = (t) => t.replace(/[^\n]/g, " ");
for (const f of globSync("**/*.html", { cwd: root })) {
  let src = readFileSync(join(root, f), "utf8");
  src = src.replace(/\{%[\s\S]*?%\}|\{\{[\s\S]*?\}\}|\{#[\s\S]*?#\}/g, blank);
  const lines = src.split("\n").map(() => "");
  const re = /\bclass\s*=\s*"([^"]*)"/g;
  let m;
  while ((m = re.exec(src))) {
    const before = src.slice(0, m.index);
    const line = before.split("\n").length - 1;
    const col = m.index - before.lastIndexOf("\n") - 1;
    const cls = m[1].replace(/\n/g, " ");
    lines[line] = lines[line].padEnd(col) + `cn("${cls}");`;
  }
  const dest = join(out, f + ".ts");
  mkdirSync(dirname(dest), { recursive: true });
  writeFileSync(dest, lines.join("\n"));
}
```

With both files in `audit/`:

```sh
npm init -y
npm install -D @shadcn/lint@0.1.0 oxlint@1.83.0 \
  tailwindcss@4.1.16 @tailwindcss/typography@0.5.19 @hasparus/tailwind@1.1.8
cp -r /path/to/ludamus/src/ludamus/client/src src   # index.css must be reachable
node extract.mjs /path/to/ludamus/src/ludamus/templates virt
npx oxlint virt --format unix
```

Django tags are blanked to spaces first so quotes inside `{% if x == "y" %}`
cannot split a class attribute. Attributes built by template logic (a
`{% if %}` around a token) are audited as whatever is left after blanking.

## Still open

Once the six branches land: decide whether `session-grid`,
`time-slot-section`, and `room-lanes-time` (live rules in the client CSS that
the audit flagged only because they sit inside nested selectors, see the
caveat at the top) should become `@utility` declarations so the rule can see
them. Low value; only worth it if the tiles get restyled anyway.
