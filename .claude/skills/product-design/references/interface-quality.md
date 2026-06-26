# Interface quality — the detail checklist

A ludamus-tailored distillation of [Vercel's Web Interface
Guidelines](https://vercel.com/design/guidelines). This is the canonical source
for the **Harden** mode: when a screen works but you want it to feel right and
survive edge cases, walk these.

It's a checklist, not a lecture — skim for what your change touches. Items marked
✅ are already enforced or built into the system; the rest are things to verify
by hand (a few are lint-rule candidates, flagged 🔎).

## Forms

The tessera renderers (`tessera_field` → `input.py`/`textarea.py`/`form_select.py`)
are the chokepoint — fixes here reach every form, so prefer changing the renderer
over patching a template.

- ✅ **16px inputs on mobile.** Inputs/textarea/select render `text-base sm:text-sm`
  so iOS Safari doesn't auto-zoom on focus. Don't reintroduce a bare `text-sm` on
  a focusable field.
- ✅ **Mobile keyboard by type.** `input.py` sets `inputmode` from the field type
  (email/tel/url/number/search).
- ✅ **No spellcheck on codes/addresses.** Email/url/tel/password inputs get
  `spellcheck="false"`.
- ✅ **Native select contrast.** `<select>` carries explicit `bg-bg-secondary`
  + `text-foreground` (fixes Windows dark-mode option lists).
- **Every control has a label.** `tessera_field` renders one; clicking it focuses
  the control. Don't ship a placeholder-only field.
- **Don't pre-disable submit.** Keep it enabled until submission begins so
  validation can surface; disable + spinner *during* flight. Focus the first
  error on submit.
- **Set `autocomplete` + meaningful `name`** so password managers and autofill
  work; allow pasting one-time codes.
- **Enter submits** a single-input form; in a textarea, Enter is a newline and
  Cmd/Ctrl+Enter submits.

## Interactions & state

- ✅ **Async announced.** Flash/toast messages use `role=status|alert` +
  `aria-live` (`components/flash-messages.html`).
- **Hit targets ≥24px (44px on mobile).** 🔎 Especially `.icon-btn` — the icon is
  ~14px, so the button needs padding to clear the target. Verify on touch.
- **Destructive actions: confirm *or* undo.** Use `confirm-dialog.html` for the
  irreversible; for reversible-but-risky, an Undo action in a toast is lighter.
  Don't confirm cheap, reversible actions.
- **Loading keeps the label.** Show a spinner *beside* the button text, don't
  swap the text for "Loading".
- **Suffix deferred actions with `…`** ("Saving…", "Rename…" when it opens a
  dialog). Use the real ellipsis character, not three dots.
- **Deep-link state.** Filters, tabs, pagination, open panels → reflect in the
  URL so Back/Forward and refresh work (see `session-filters.ts`, `tabs.ts`).
- **Use `<a>`/`{% url %}` for navigation** so Cmd/middle/right-click work; buttons
  for actions.

## Motion

- ✅ **Reduced-motion respected** (`flash.ts`); prefer CSS > WAAPI > JS libs.
- ✅ **No `transition: all`.** 🔎 Enforced by `rules/no-transition-all.yml`. List
  the properties that actually change (`transition-[border-color,box-shadow]`,
  `transition-shadow`, or Tailwind's curated `transition`).
- **Animate `transform`/`opacity`**, not layout-triggering properties. Match
  easing to what changes; strong ease-out on exits. Anchor motion to its origin.

## Content, copy & i18n

- See [copy.md](copy.md) for voice and the Polish term table.
- **Tabular numerals for figures.** 🔎 Add `tabular-nums` to counts/capacity that
  sit in a list or update live (done: enrollment capacity in `enroll_select.html`)
  so digits don't jitter.
- **Locale-format** dates, times, numbers, currency. Wrap brand/code tokens in
  `translate="no"`; keep units together with `&nbsp;` ("10&nbsp;MB").
- **Status needs more than color** — pair the color with text/icon (our alerts do).
- **Handle short / average / very long** user content without breaking layout
  (cross-ref [reachable-states.md](reachable-states.md)).

## Layout, a11y & perf (spot-check)

- **Semantic elements first** (`button`, `a`, `label`, `h1–h6`, `table`) before
  ARIA roles. Headings hierarchical; "Skip to content" present.
- **Visible focus rings** (`:focus-visible`); full keyboard operability.
- **Verify mobile / laptop / ultra-wide.** Reserve image dimensions to avoid
  layout shift; lazy-load below-the-fold.
- **Target POST/PATCH/DELETE under ~500ms.**

When you find a recurring miss here, promote it: a deterministic one becomes a
`rules/*.yml` lint rule; a judgment one gets a line in [patterns.md](patterns.md)
or an entry in [exemplars.md](exemplars.md).
