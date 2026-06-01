# Plan: Import editor — summary table + single-field editor

Each step ships something demoable in the UI.
Existing scrollable editor stays usable until Step 8 retires it.

## Step 1 — `confirmed` flag + summary table

- Add optional `confirmed: bool = False` to the pydantic model behind
  `questions.<title>` entries; ensure JSON tab roundtrips it.
- Render a new read-only summary table on the import page above the existing
  recipe editor. Columns: status, question, mapping, details.
- Status is derived: `confirmed` → confirmed; `ignore: true` → ignored;
  otherwise unconfirmed.
- Verify: edit `settings.json` JSON tab to add `"confirmed": true` to a row,
  reload → summary shows the confirmed glyph.

## Step 2 — Click summary row → single-field editor (full reload)

- Extract the per-row editor markup into a template partial.
- Add `?edit=<index>` query handling on the import page: when present, render
  only that row's editor (no table, no other rows) plus a "Back to summary"
  link. No HTMX yet — plain page reload.
- Click summary row links to `?edit=N`.
- Verify: click a row → editor for that question; "Back" → summary.

## Step 3 — HTMX-swap the editor in place

- Replace the full reload with `hx-get` returning the editor partial; swap the
  summary/editor region. "Back to summary" swaps back via `hx-get`.
- Verify: clicking is instant, no full reload; back button still works
  reasonably (URL stays the same).

## Step 4 — Nav panel: Prev / Next / Cancel / dropdown

- Add nav panel above editor: Prev, "Question N of M ▾" dropdown, Next, Cancel.
- Each is an `hx-get` for a different `?edit=<index>` partial.
- No Save yet; no dirty guard yet — user must Cancel back to summary.
- Verify: walk through questions with Prev/Next, jump via dropdown, Cancel
  returns to summary.

## Step 5 — Review tab + per-row Save (retires the bulk editor)

Combines original Step 5 (per-row Save) with original Step 8 (retire bulk
editor) and splits the editor onto its own tab, since the operator wanted a
clean "browse questions one by one" surface.

- Add a new "Review" tab next to Proposal / JSON / Import run. Path:
  `/event/<slug>/import/<int:pk>/review/`, name `panel:import-review`.
- Move the single-row editor and Prev/Next/dropdown/Cancel nav from the
  Proposal tab onto the Review tab. Review tab default (no `?edit`) lands on
  the first question.
- Proposal tab is now summary-only — the always-rendered scrollable recipe
  table and its bulk Save button go away (original Step 8).
- Clicking a question in the summary HTMX-swaps to the Review tab (`hx-get`
  the review URL with `?edit=N`, swap `#import-recipe-region`, push that URL).
- Cancel in the nav links back to the Proposal/Summary tab.
- Add a Save button to the nav: `hx-post` of the current row's form fields to
  a new per-row save endpoint. Endpoint writes that row's edits to
  `settings.json`, sets `confirmed: true`, and returns `HX-Redirect` to the
  Proposal tab so the operator sees the row's new ✓.
- Verify: open Review tab → edit a row → Save → land on summary with ✓ for
  that row; Cancel returns without persisting; reload preserves the edits.

## Step 6 — Dirty guard

- Client-side: snapshot form values on editor render; on Prev/Next/Cancel/
  dropdown/row-click, compare; if dirty, show native `confirm()`:
  "Unsaved changes. Save before switching?" with [Save] [Discard] [Stay].
  - Save: submit the current row, then navigate.
  - Discard: navigate without saving.
  - Stay: do nothing.
- Verify: edit a field, click Next → dialog; each choice behaves correctly.

## Step 7 — Jump to next unconfirmed

- Add "Jump to next unconfirmed" button. Server computes next index after the
  current one whose entry lacks `confirmed: true`; wraps to start.
- If nothing unconfirmed: button is disabled (or shows "All confirmed").
- Verify: walk through unconfirmed rows until none left; button disables.

## Step 8 — Retire the old inline editor

- Remove the always-rendered scrollable recipe table; summary is the sole
  entry point. Delete the now-unused template fragments and view branches.
- Verify: import page only shows the summary by default; editor is reached
  only via click/swap.

## Step 9 — Refetch form button

- Add "Refetch form" button in the summary toolbar. On click: native
  `confirm()` with the exact wording from the shape (count of mappings, count
  of confirmed). On accept: call the form-pull integration, regenerate
  `questions` entries, drop every `confirmed`. Preserve `definitions`.
- Verify: refetch with some confirmed rows → all reset to unconfirmed;
  `definitions` untouched.

## Step 10 — Run-import gate

- Where the "Run import" action lives today (import-run tab), block the
  submission if any `questions.<title>` lacks `confirmed: true`. Render
  message: "X questions are unconfirmed. Review them first." with a link back
  to the summary.
- Verify: try to run with unconfirmed rows → blocked; confirm them all →
  unblocked.

## Verification at every step

- `mise run check` (format + lint) passes
- `mise run test` passes; new behavior covered by integration tests in the
  layer that owns it (gates/links/templates → integration tests per
  `docs/TESTING_STRATEGY.md`)
- Manually click the affected page in the browser to confirm the demoable
  behaviour for the step

## Out of scope (deferred)

- Deep links to a specific question
- Bulk-confirm / bulk-edit
- Auto-confirm if untouched after refetch
- Custom modal replacing native `confirm()`
