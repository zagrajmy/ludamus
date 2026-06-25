# Exemplars — patterns worth repeating (and mistakes to avoid)

Concrete, in-repo examples beat abstract advice. Each entry points at real code
so you can copy the shape. When you ship a good decision (or catch a bad one in
review), add it here — that's how the next agent inherits it.

## Do this

- **Icon-only buttons carry a label.** Every `.icon-btn` in the codebase pairs
  the `{% icon %}` with a `<span class="sr-only">{% translate "…" %}</span>`.
  See `src/ludamus/templates/crowd/user/connected.html` (Edit/Delete row
  actions) and the gallery in `src/ludamus/templates/design.html`. This is now
  enforced by `rules/icon-btn-accessible-name.yml`.
- **Let tessera collapse single-choice fields.** A required field with one
  possible value renders no widget — `render_forced_choice` /
  `single_required_choice` in
  `src/ludamus/adapters/web/django/templatetags/tessera/form_select.py`. This is
  the house answer to "don't show a form with one selectable option."
- **Tables go through `{% tessera_table %}`.** It supplies the card chrome and
  responsive scroll wrapper, so the table is consistent and works on narrow
  screens without per-page CSS.
- **Theming via utilities, not inline vars.** Templates use `text-foreground`,
  `bg-bg-secondary`, `border-border` rather than inline `style="…var(--color-…)"`.
- **Screenshots in the PR.** `docs/assets/pr-330-cover-screenshots/` shows the
  expected artifact: before/after PNGs of each affected page, captured with
  `mise run shots`. Visual PRs include these.
- **UX audits as a first-class task.** PR #431 (`claude/app-ux-audit-*`) treated
  "is this respectful of the user?" as real work, not polish. That's the bar.

## Avoid this

- **Hand-rolled form controls.** Writing `<input>`/`<select>`/styled `<button>`
  by hand when a tessera tag exists. It drifts from the system and skips the
  accessibility/error wiring you'd get for free.
- **A `<select>` for 2–3 fixed options.** Hides the choices behind a click; use
  a radio group so they're all visible (see patterns.md).
- **Confirm steps on cheap, reversible actions.** A modal for something a user
  does dozens of times a day, or that's trivially undone, is friction. Reserve
  confirmation for the irreversible.
- **Generic action labels.** "Submit" / "OK" / "Confirm" instead of Verb + Noun.
- **Shipping the happy path only.** No empty/error/narrow-viewport state. See
  reachable-states.md.

## When you add an entry

Keep it to a sentence or two and a `path` or `PR #`. If the lesson is
mechanical and detectable, prefer turning it into a `rules/*.yml` lint rule and
just linking it here — deterministic beats documented.
