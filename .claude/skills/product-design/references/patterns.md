# Patterns — tessera components and which one to use

The design system lives in
`src/ludamus/adapters/web/django/templatetags/tessera/`. Load it with
`{% load tessera %}`. The live gallery is at `/design/`
(`src/ludamus/templates/design.html`) — open it to see every component rendered.

Rule of thumb: **reach for a tag before raw HTML, and hierarchy/spacing before a
container.** If you're writing `<input>`, `<select>`, or a bare styled
`<button>` by hand, check the table first.

## Component catalog

| Need | Use | Notes |
| --- | --- | --- |
| A whole form | `{% tessera_form form %}` | Renders labels, fields, help text, and errors. `layout="horizontal"` available. Use this before composing fields by hand. |
| One field | `{% tessera_field form.name %}` | Dispatches to the right renderer (input/textarea/select/checkbox/file) by field type. |
| Form-level errors | `{% tessera_errors form %}` | Non-field errors as an alert. |
| Action / link button | `{% tessera_button "Save" %}` | `href=` makes it a link; `variant="primary"/"secondary"/"danger"`, `size=`, `icon=`, `disabled`, `full_width_mobile`. The raw classes are `.btn .btn-primary` etc. |
| Icon | `{% icon "calendar" %}` | Heroicons. `variant="outline"/"solid"/"mini"/"micro"`, `class="w-5 h-5"`. |
| Icon-only button | `.icon-btn` + `{% icon %}` + `<span class="sr-only">` | **Must** carry an accessible name (`sr-only` span or `aria-label`). Enforced by `rules/icon-btn-accessible-name.yml`. Variants: `.icon-btn-primary`, `.icon-btn-danger`. |
| Custom `<select>` | `{% select id=.. name=.. %}<option>…{% end_select %}` | Slot-based, for selects not backed by a form field. Registered as a djlint custom block. |
| Data table | `{% tessera_table %}<thead>…<tbody>…{% end_tessera_table %}` | Wraps your `<thead>/<tbody>` in a card + responsive scroll container. Don't hand-build the card chrome. |
| Tab navigation | `{% tabs %}{% tab "key" icon=.. href=.. active=.. %}Label{% end_tab %}{% end_tabs %}` | For navigation between related views. Tabs are *navigation* — use links, not buttons. |
| Avatar | `{% include "components/avatar.html" with user=.. size="size-12" %}` | Size via Tailwind `size-*`. |

Other ready-made component templates live in
`src/ludamus/templates/components/` (alert, card, file-dropzone, choice-group,
visibility badges, …). Prefer including those over re-creating their markup.

## Which component — the decisions

- **Navigation vs action.** A thing that takes you somewhere is a link/tab
  (`href`). A thing that *does* something is a button (`type="submit"` /
  `type="button"`). Don't style a link as a primary button for a destructive
  action, and don't use a button where a link belongs.
- **2–3 static options → radio, not select.** A `<select>` hides options behind
  a click. For a small fixed set (visibility: public/private; yes/no/maybe),
  render them as a radio group (`choice-group.html` / `RadioSelect`) so all
  options are visible at once. Reserve `<select>` for long or dynamic lists.
- **One required option → no widget at all.** If a required choice has a single
  possible value, don't render a picker. tessera already does this via
  `render_forced_choice` / `single_required_choice` — let it. Showing a form
  with one selectable option is the canonical "are we torturing the user?"
  defect from CLAUDE.md.
- **One primary action per view.** Make the user's main action unmistakable;
  everything else is `variant="secondary"`. Two competing primary buttons means
  neither reads as primary.
- **Containers are a last resort.** Group with spacing and type hierarchy first.
  Add a `card` only when the content is genuinely a separable unit. Nested cards
  are almost always a hierarchy problem.

## Theming / styling

- Use Tailwind utilities, not inline CSS variables. `--theme-*` is gone;
  `--color-*` is the palette and is exposed as utilities (`text-foreground`,
  `bg-bg-secondary`, `border-border`). Inline `style="…var(--color-…)"` /
  `var(--theme-…)` is blocked by `rules/no-inline-color-var.yml` /
  `rules/no-inline-theme-var.yml`.
- Spacing/sizing comes from the Tailwind scale; don't invent magic pixel values.
- One brand font (Outfit) by design — don't add a second.
