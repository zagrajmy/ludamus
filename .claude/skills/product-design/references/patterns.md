# Patterns — tessera components and which one to use

The design system lives in
`src/ludamus/gates/web/django/templatetags/tessera/`. Load it with
`{% load tessera %}`. The live gallery is at `/design/`
(`src/ludamus/templates/design.html`) — open it to see every component rendered.

Rule of thumb: **reach for a tag before raw HTML, and hierarchy/spacing before a
container.** If you're writing `<input>`, `<select>`, or a bare styled
`<button>` by hand, check the table first.

## Component catalog

| Need | Use | Notes |
| --- | --- | --- |
| A whole form | `{% tessera_form form %}` | Renders labels, fields, help text, and errors. `layout="horizontal"` available. Use this before composing fields by hand. |
| One field | `{% tessera_field form.name %}` | Dispatches to the right renderer (input/textarea/select/checkbox/file) by field type. `label_action_template=` places a small action beside the label. |
| Hex color | `{% tessera_field form.color %}` with `TextInput(attrs={"type": "color"})` | Text value plus synchronized native picker. Empty stays unset; the text field works without JavaScript. |
| Form-level errors | `{% tessera_errors form %}` | Non-field errors as an alert. |
| Action / link button | `{% tessera_button "Save" %}` | `href=` makes it a link; `variant="primary"/"secondary"/"danger"`, `size=`, `icon=`, `disabled`, `full_width_mobile`. The raw classes are `.btn .btn-primary` etc. |
| Icon | `{% icon "calendar" %}` | Heroicons. `variant="outline"/"solid"/"mini"/"micro"`, `class="w-5 h-5"`. |
| A few big choices that each go somewhere | `{% tessera_link_tile id_prefix=.. href=.. title=.. description=.. icon=.. %}` | A link tile with a title, a line of help and an icon in a warm tile that turns coral on hover and focus. The title names the link and the help describes it. Lay 2–3 out in a grid, as the feed's Organize dialog does. |
| Dialog close (×) | `{% tessera_dialog_close_button "dialog-id" %}` | The clear `.icon-btn` in a modal's header, named "Close", wired to `modal.ts` through `data-modal-close`. Use it rather than hand-rolling the × or reaching for `tessera_icon_button`, which is sized and styled for sheets and panels. |
| Choice that applies at once | `{% tessera_choice_buttons name="…" selected=current %}` + `{% tessera_choice_button value %}` | A segmented row of submit buttons inside a `<form>` and a `<fieldset>` with a legend; `aria-pressed` marks the current one. For two to four options where picking is the whole action (the profile's language). For a choice saved with other fields use a radio; for switching views use `{% tabs variant="segment" %}`. |
| Icon-only button | `.icon-btn` + `{% icon %}` + `<span class="sr-only">` | **Must** carry an accessible name (`sr-only` span or `aria-label`). Enforced by `rules/icon-btn-accessible-name.yml`. Variants: `.icon-btn-primary`, `.icon-btn-danger`. |
| Custom `<select>` | `{% select id=.. name=.. %}<option>…{% end_select %}` | Slot-based, for selects not backed by a form field. Registered as a djlint custom block. |
| Searchable select | `{% tessera_combobox id=.. name=.. %}<option>…{% end_tessera_combobox %}` | For lists too long to scroll. Ships a `<select>` the browser upgrades to an ARIA combobox (typeahead, `aria-activedescendant`, top-layer popup); the select stays the value, so forms and `change` listeners are unaffected and it still works without JS. `placeholder=`, `empty_text=`, `toggle_label=` take the copy. djlint custom block. |
| Multi-select with chips | `{% tessera_combobox id=.. name=.. multiple=True chips=True %}<option>…{% end_tessera_combobox %}` | A form field with several picks: each pick is a removable chip beside the input (Backspace removes the last, arrow keys walk the chips, removals are announced). Built on UI SDK's Combobox (`components/combobox-chips.html`). `described_by=` points the input at the field's error. Use the plain `multiple=True` combobox for a filter whose picks already show elsewhere on the page. |
| Number stepper | `{% include "components/stepper-field.html" with name=.. label=.. min=.. max=.. %}` | − / + around a number input, built on UI SDK's Number Input: a button disables at its bound, repeats while held, and stays out of the tab order (the input's arrow keys step it). Pass `label` (or `aria_label`) so the buttons are named after their field. |
| Data table | `{% tessera_table %}<thead>…<tbody>…{% end_tessera_table %}` | Wraps your `<thead>/<tbody>` in a card + responsive scroll container. Don't hand-build the card chrome. A hoverable row's background follows Edit / Details: mark that link `data-row-action`. |
| Tab navigation | `{% tabs %}{% tab "key" icon=.. href=.. active=.. %}Label{% end_tab %}{% end_tabs %}` | For navigation between related views. Tabs are *navigation* — use links, not buttons. |
| Command menu entry | A link or button inside a `[data-command-group]` in `components/command-menu.html` | The Ctrl/⌘K menu (cmdk) lists those elements and clicks the one picked, so an entry is a real `<a href>` or a `<button>` in a form. Start it with an `{% icon … variant="mini" %}`; `aria-pressed="true"` marks the current choice; `data-keywords=` adds search words; a `<span data-command-hint>` shows muted text at the row's end. Wrap choices of one setting in `[data-command-submenu]` to get one row that opens its own list. Entries that need a query (what a person may create, their events and encounters) go in `command-menu-entries.html`, fetched on first open; mark a long group `data-command-search-only`. No TypeScript change needed. |
| Avatar | `{% include "components/avatar.html" with user=.. size="size-12" %}` | Size via Tailwind `size-*`. |

Other ready-made component templates live in
`src/ludamus/templates/components/` (card, file-dropzone, choice-group,
visibility badges, …). Prefer including those over re-creating their markup.

Static message banners are banned in page templates (`rules/no-static-alerts.yml`).
Put status beside the relevant item, guidance beside the field, and plans on the
dashboard with a title, time, and link. Do not recreate colored banner boxes with
utilities. Form errors use `tessera_errors`; action feedback uses Django messages
in the shared, dismissible toaster. Only the flash renderer and design gallery
may use the alert component directly.

## Which component — the decisions

- **Navigation vs action.** A thing that takes you somewhere is a link/tab
  (`href`). A thing that *does* something is a button (`type="submit"` /
  `type="button"`). Don't style a link as a primary button for a destructive
  action, and don't use a button where a link belongs.
- **2–3 static options → radio, not select.** A `<select>` hides options behind
  a click. For a small fixed set (visibility: public/private; yes/no/maybe),
  render them as a radio group (`choice-group.html` / `RadioSelect`) so all
  options are visible at once. Reserve `<select>` for long or dynamic lists.
- **Past ~15 options → combobox, not select.** Scrolling stops being a way to
  find a name once the list is long (an event's facilitators, a venue's rooms).
  `{% tessera_combobox %}` lets people type instead, and its filtering folds
  diacritics, so "wlodarczyk" finds "Włodarczyk". Below that, a plain
  `{% select %}` is less machinery for the same job.
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
- **Cloud vs definition list.** Tokens that already carry their kind (icon on
  a chip) live in one wrap. Restacking them into labelled rows is a `dl` —
  a different component. Overflow is another token (`+N`), not a row per field.
- **Hoverable table rows have a default action.** If the row highlights on
  hover, clicking the background goes to Edit or Details. Put `data-row-action`
  on that link so Delete, checkboxes, and menus keep their own targets. Shown
  on `/design`.

## Theming / styling

- Use Tailwind utilities, not inline CSS variables. `--theme-*` is gone;
  `--color-*` is the palette and is exposed as utilities (`text-foreground`,
  `bg-bg-secondary`, `border-border`). Inline `style="…var(--color-…)"` /
  `var(--theme-…)` is blocked by `rules/no-inline-color-var.yml` /
  `rules/no-inline-theme-var.yml`.
- Spacing/sizing comes from the Tailwind scale; don't invent magic pixel values.
- One brand font (Outfit) by design — don't add a second.
