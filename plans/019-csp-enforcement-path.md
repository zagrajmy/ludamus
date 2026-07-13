# Plan 019: Tighten CSP toward enforcement (nonces, hx-on, gated flip)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md` — unless a reviewer dispatched you
> and told you they maintain the index.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat ab380f1c..HEAD -- \
>   src/ludamus/edges/settings.py \
>   src/ludamus/templates/base.html \
>   src/ludamus/templates/components/theme_script.html \
>   src/ludamus/templates/panel/base.html \
>   src/ludamus/templates/500_dynamic.html \
>   src/ludamus/templates/notice_board/index.html \
>   src/ludamus/templates/notice_board/detail.html \
>   src/ludamus/templates/panel/facilitator-merge.html \
>   src/ludamus/templates/panel/session-field-create.html \
>   src/ludamus/templates/panel/personal-data-field-create.html \
>   src/ludamus/templates/panel/proposal-edit.html \
>   src/ludamus/templates/panel/cfp-edit.html \
>   src/ludamus/templates/components/checkbox-field.html \
>   src/ludamus/templates/panel/parts/timetable-session-detail.html \
>   src/ludamus/templates/multiverse/panel/connections/edit.html \
>   tests/integration/web/test_security_headers.py
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (touching every inline `<script>` and every `hx-on:`
  attribute in the templates; a missed site breaks a page once
  `'unsafe-inline'`/`'unsafe-eval'` are dropped)
- **Depends on**: plans/007-csp-report-only.md (shipped: report-only
  header, DONE)
- **Category**: security
- **Planned at**: commit `ab380f1c`, 2026-07-13

## Why this matters

Plan 007 shipped `Content-Security-Policy-Report-Only` with
`'unsafe-inline'` and `'unsafe-eval'` in `script-src` so it could ship
without any risk of breaking pages. Those two tokens are also exactly
what make an eventual enforcing CSP useless as an XSS layer: a script
injected through a `mark_safe`/sanitizer gap runs anyway under either
token. Removing them requires nonce-ifying every inline `<script>`
block and eliminating `hx-on:` attributes (htmx evaluates their body
via `Function`, which needs `'unsafe-eval'`). Both are mechanical and
carry no dependency on production data, so they can happen now. The
enforcement flip itself — replacing `SECURE_CSP_REPORT_ONLY` with
`SECURE_CSP` — is a different kind of change: it can turn a policy gap
into a broken page in production. The maintainer's call is to do that
only after reviewing real report-only violation data, which does not
exist yet. This plan separates the two so an executor can do the safe
mechanical work now and is blocked, by an explicit STOP condition,
from doing the risky flip early.

## Current state

- `src/ludamus/edges/settings.py:307-323` — `CSP_REPORT_ONLY_POLICY`,
  the policy shipped by plan 007:

  ```python
  CSP_REPORT_ONLY_POLICY: dict[str, list[str]] = {
      "default-src": [CSP.SELF],
      "script-src": [CSP.SELF, CSP.UNSAFE_INLINE, CSP.UNSAFE_EVAL],
      "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
      "img-src": [CSP.SELF, "data:", "https:"],
      "font-src": [CSP.SELF],
      "connect-src": [CSP.SELF],
      "object-src": [CSP.NONE],
      "base-uri": [CSP.SELF],
      "form-action": [CSP.SELF],
      "frame-ancestors": [CSP.NONE],
  }
  ```

  Only `SECURE_CSP_REPORT_ONLY = CSP_REPORT_ONLY_POLICY` is set inside
  `if IS_PRODUCTION:` (`settings.py:364`); `SECURE_CSP` is never
  assigned anywhere (`grep -c "SECURE_CSP =" src/ludamus/edges/settings.py`
  → 0).
- `src/ludamus/edges/settings.py:123-125` — `MIDDLEWARE` already has
  `"django.middleware.csp.ContentSecurityPolicyMiddleware"` installed
  unconditionally, right after `SecurityMiddleware`.
- `src/ludamus/edges/settings.py:162-186` — `TEMPLATES[0]["OPTIONS"]
  ["context_processors"]` does **not** include
  `"django.template.context_processors.csp"`:

  ```python
  "context_processors": [
      "django.template.context_processors.request",
      "django.template.context_processors.media",
      "ludamus.gates.web.django.context_processors.sites",
      "ludamus.gates.web.django.context_processors.support",
      "ludamus.gates.web.django.context_processors.static_version",
      "ludamus.gates.web.django.context_processors.current_user",
      "django.contrib.auth.context_processors.auth",
      "django.contrib.messages.context_processors.messages",
  ],
  ```

  Without that context processor, templates have no `{{ csp_nonce }}`
  variable to read.
- **The nonce mechanism, verified in the installed Django 6.0.7**
  (`.venv/lib/python3.14/site-packages/django/`):
  - `middleware/csp.py` — `ContentSecurityPolicyMiddleware.process_request`
    sets `request._csp_nonce = LazyNonce()` on every request (a lazy,
    cryptographically-random `secrets.token_urlsafe(16)` string,
    generated only if actually read). `process_response` calls
    `build_policy(config, nonce)` for both the enforce and report-only
    configs, and `build_policy` (`utils/csp.py:88-119`) replaces the
    `CSP.NONCE` sentinel value in a directive's list with
    `'nonce-<value>'` if the sentinel is present and a nonce was
    generated, else drops the sentinel entirely.
  - `template/context_processors.py:93-97`:

    ```python
    def csp(request):
        """
        Add the CSP nonce to the context.
        """
        return {"csp_nonce": get_nonce(request)}
    ```

    (`get_nonce` from `django.middleware.csp` reads
    `request._csp_nonce`.) This is the `django.template.context_processors.csp`
    entry that must be added to `TEMPLATES`.
  - Per Django's own docstring on `LazyNonce`
    (`utils/csp.py:52-68`), the template usage is:
    `<script{% if csp_nonce %} nonce="{{ csp_nonce }}"{% endif %}>`
    — the nonce is generated lazily on first read, so adding the
    attribute is what triggers generation; pages with no inline
    script pay nothing.
  - To have the nonce actually appear on a directive, the settings
    dict lists `CSP.NONCE` as one of the `script-src` values (it is a
    sentinel string `"<CSP_NONCE_SENTINEL>"`, not a real nonce);
    `build_policy` substitutes it per request.
- **Inline `<script>` blocks that need `nonce="{{ csp_nonce }}"`**
  (own grep, `grep -rn "<script" src/ludamus/templates/` filtered to
  blocks without an external `src=`) — 14 tags across 12 files:
  - `src/ludamus/templates/base.html:43-54` — theme FOUC-prevention
    script, present on every page that extends `base.html`.
  - `src/ludamus/templates/components/theme_script.html:1-83` —
    the full theme-switcher script; included via
    `{% include "components/theme_script.html" %}` at
    `base.html:136`, so it renders on every page too (Django
    `{% include %}` inherits the parent context, so `csp_nonce` is
    visible inside it once the context processor is registered).
  - `src/ludamus/templates/500_dynamic.html:12-21` — a duplicate of
    the theme FOUC script for the custom 500 page. This page is
    rendered by Django's error-handling path; confirm at
    execution time (Step 5's verify) that `request._csp_nonce` is
    still populated for 500 responses — if the CSP middleware does
    not run on this path, note it as a residual `'unsafe-inline'`
    exception in this one file rather than guessing.
  - `src/ludamus/templates/notice_board/index.html:63-70` —
    dismiss-banner script inside `{% block extra_scripts %}`.
  - `src/ludamus/templates/notice_board/detail.html:248-...` —
    encounter countdown timer script.
  - `src/ludamus/templates/panel/facilitator-merge.html:113-...` —
    facilitator search/select-all script.
  - `src/ludamus/templates/panel/session-field-create.html:161-...`
    — field-type conditional-visibility script.
  - `src/ludamus/templates/panel/personal-data-field-create.html:143-...`
    — same pattern as session-field-create.html.
  - `src/ludamus/templates/panel/proposal-edit.html:308-...` —
    facilitator search script.
  - `src/ludamus/templates/panel/cfp-edit.html:167-...` — duration
    add/remove script.
  - `src/ludamus/templates/panel/cfp-edit.html:384-393` — a small
    inline script that only sets `window.__fieldPickerI18n = {...}`
    (a data blob, not logic).
  - `src/ludamus/templates/panel/cfp-edit.html:394-...` — the
    field-picker script that reads `window.__fieldPickerI18n`.
  - `src/ludamus/templates/panel/base.html:15-...` — restores
    `panel-sidebar-folded`/`panel-cat-*` UI state from
    `localStorage` before paint, inside `{% block extra_head %}`.
  - `src/ludamus/templates/panel/base.html:383-...` — `<script
    type="module">`, Escape-key handler for the sidebar overlay.
    `type="module"` scripts also need the `nonce` attribute; the
    `type` attribute does not exempt them.
- **`hx-on:` attributes — confirmed in active use, 11 occurrences,
  3 files** (own grep, `grep -rn "hx-on" src/ludamus/templates/`):
  - `src/ludamus/templates/components/checkbox-field.html:20`:

    ```django
    {% if hx_on_change|default:"" %}hx-on:change="{{ hx_on_change }}"{% endif %}>
    ```

    Only one caller passes `hx_on_change`:
    `src/ludamus/templates/multiverse/panel/connections/edit.html:31`,
    which passes a JS expression toggling `aria-expanded`/
    `aria-required` on a sibling field.
  - `src/ludamus/templates/panel/parts/timetable-session-detail.html:63,73`
    — `hx-on::after-request="if(event.detail.successful){htmx.ajax(...)}"`,
    re-fetching a pane after a successful htmx request.
  - `src/ludamus/templates/panel/base.html:134,150,164,195,241,280,307,333`
    — 8 occurrences, all inline JS in `hx-on:click="..."` /
    `hx-on:change="..."`. Four are byte-identical category-collapse
    toggles (`:195,241,280,307`); the other four are distinct:
    sidebar toggle (`:134`), sidebar-fold persistence (`:150`),
    event-switcher navigation (`:164`), and a second sidebar-toggle
    variant that also toggles the overlay (`:333`).

  htmx evaluates `hx-on:*` attribute bodies via the `Function`
  constructor at runtime — this is why `script-src` currently carries
  `'unsafe-eval'` (see plan 007's comment,
  `src/ludamus/edges/settings.py:307-311`). This plan's premise that
  the grep "might come back empty" does **not** hold: `hx-on:` is real
  and load-bearing in this codebase. `'unsafe-eval'` cannot be dropped
  without first converting all 11 sites to real event listeners
  (typically via a small same-origin `<script nonce>` or a Vite
  module that does `element.addEventListener(...)`), which is Step
  Group B below.
- `tests/integration/web/test_security_headers.py` — the existing
  header tests (`TestCSPReportOnlyHeader`), model for the new
  assertions:

  ```python
  REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
  ENFORCE_HEADER = "Content-Security-Policy"


  class TestCSPReportOnlyHeader:
      URL = reverse("web:index")

      def test_header_sent_when_production_policy_active(
          self, client, settings
      ):
          settings.SECURE_CSP_REPORT_ONLY = CSP_REPORT_ONLY_POLICY
          response = client.get(self.URL)
          assert_response(response, HTTPStatus.FOUND, url=reverse("web:events"))
          header = response.headers[REPORT_ONLY_HEADER]
          assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in header
          ...
  ```

  Extend this file, don't replace it — the `test_no_csp_headers_by_default`
  regression guard must keep passing unmodified.
- Repo rules that apply: NEVER add `noqa` / `type: ignore` / pylint
  directives; mypy runs strict; functions with 3+ parameters take
  keyword-only args; avoid docstrings; new tests for `gates` /
  templates / settings-served headers are **integration** tests (see
  `docs/TESTING_STRATEGY.md`); use `assert_response`, never manual
  status asserts.
- Environment notes: `export MISE_ENV=sandbox` before any mise command
  in this container; prefix test/check runs with
  `PATH="$(pwd)/.venv/bin:$PATH"`. The CI-style gate is `mise run
  check` (there is no `prcheck` task).

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise install && poetry install` | exit 0 |
| All Py tests | `mise run test:py` | all pass |
| CI-style checks | `mise run check` | exit 0 |
| One test file | `.venv/bin/pytest tests/integration/web/test_security_headers.py` | all pass |
| Markdown lint | `mise exec -- markdownlint-cli2 "plans/*.md"` | 0 errors |

## Suggested executor toolkit

- `product-design` skill — not needed for Step Groups A/B (no visible
  UI change, only attribute plumbing); do not invoke it for this plan.
- `docs/agents/architecture.md` — background on the GLIMPSE layers if
  any step turns up an unexpected import-linter violation (unlikely;
  this plan only touches `edges/settings.py`, templates, and tests).

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/edges/settings.py`
- `src/ludamus/templates/base.html`
- `src/ludamus/templates/components/theme_script.html`
- `src/ludamus/templates/panel/base.html`
- `src/ludamus/templates/500_dynamic.html`
- `src/ludamus/templates/notice_board/index.html`
- `src/ludamus/templates/notice_board/detail.html`
- `src/ludamus/templates/panel/facilitator-merge.html`
- `src/ludamus/templates/panel/session-field-create.html`
- `src/ludamus/templates/panel/personal-data-field-create.html`
- `src/ludamus/templates/panel/proposal-edit.html`
- `src/ludamus/templates/panel/cfp-edit.html`
- `src/ludamus/templates/components/checkbox-field.html`
- `src/ludamus/templates/panel/parts/timetable-session-detail.html`
- `src/ludamus/templates/multiverse/panel/connections/edit.html`
- New same-origin JS module(s) under `src/` (Vite source), created
  only as needed by Step Group B (see Step 4)
- `tests/integration/web/test_security_headers.py`

**Out of scope** (do NOT touch, even though they look related):

- Setting `SECURE_CSP` (the enforcing header) — Step Group C is
  GATED; see STOP conditions. Do not flip enforcement in this pass.
- A `report-uri` / `report-to` ingestion endpoint or third-party
  collector — Step Group C only writes the **decision note**; wiring
  an endpoint is a separate, human-scoped follow-up (plan 007's
  Maintenance notes already flagged this as deferred).
- Narrowing `img-src https:` to concrete hosts — that requires
  reviewing production report-only data too; out of scope here.
- Any behavior change to the scripts themselves beyond adding a
  `nonce` attribute (Group A) or converting `hx-on:` bodies into
  `addEventListener` calls with identical logic (Group B). No
  refactors, no new features.
- `markdown_tags.py`, `mills/legacy.py`, the tessera templatetags,
  the nh3 sanitizer — untouched, as in plan 007.

## Git workflow

- Commit per step group; message style example:
  `feat(edges): serve CSP nonces for inline scripts`.
- End every commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Register the `csp` context processor

In `src/ludamus/edges/settings.py`, add
`"django.template.context_processors.csp"` to
`TEMPLATES[0]["OPTIONS"]["context_processors"]` (`settings.py:169-178`),
e.g. next to `"django.template.context_processors.request"`.

**Verify**: `mise run test:py` → all pass (the context processor is
additive; no template currently reads `csp_nonce`, so no behavior
changes yet).

### Step 2: Add `nonce="{{ csp_nonce }}"` to every inline `<script>`

For each of the 14 `<script>` tags enumerated in "Current state"
(`base.html:43`, `components/theme_script.html:1`,
`500_dynamic.html:12`, `notice_board/index.html:63`,
`notice_board/detail.html:248`, `panel/facilitator-merge.html:113`,
`panel/session-field-create.html:161`,
`panel/personal-data-field-create.html:143`,
`panel/proposal-edit.html:308`, `panel/cfp-edit.html:167`,
`panel/cfp-edit.html:384`, `panel/cfp-edit.html:394`,
`panel/base.html:15`, `panel/base.html:383`), change the opening tag
to include the nonce, e.g.:

```django
<script nonce="{{ csp_nonce }}">
```

and for the `type="module"` tag at `panel/base.html:383`:

```django
<script type="module" nonce="{{ csp_nonce }}">
```

Do not add `{% if csp_nonce %}` guards — the nonce is generated lazily
on first read regardless, and every one of these pages is rendered
through the full middleware chain (not `500_dynamic.html` — verify
that one specifically per the note in "Current state"; if
`request._csp_nonce` is unset there, leave that single script on a
documented exception rather than breaking the error page).

**Verify**:
`grep -c 'nonce="{{ csp_nonce }}"' src/ludamus/templates/base.html
src/ludamus/templates/components/theme_script.html
src/ludamus/templates/panel/base.html
src/ludamus/templates/notice_board/index.html
src/ludamus/templates/notice_board/detail.html
src/ludamus/templates/panel/facilitator-merge.html
src/ludamus/templates/panel/session-field-create.html
src/ludamus/templates/panel/personal-data-field-create.html
src/ludamus/templates/panel/proposal-edit.html
src/ludamus/templates/panel/cfp-edit.html` → each file's count matches
its number of inline `<script>` tags from "Current state" (`cfp-edit.html`
→ 3, `panel/base.html` → 2, all others → 1), except `500_dynamic.html`
per the note above. `mise run test:py` → all pass.

### Step 3: Switch `script-src` from `'unsafe-inline'` to the nonce

In `src/ludamus/edges/settings.py`, change `CSP_REPORT_ONLY_POLICY`'s
`script-src` entry (`settings.py:314`) from:

```python
"script-src": [CSP.SELF, CSP.UNSAFE_INLINE, CSP.UNSAFE_EVAL],
```

to:

```python
"script-src": [CSP.SELF, CSP.NONCE, CSP.UNSAFE_EVAL],
```

Keep `CSP.UNSAFE_EVAL` — Step Group B has not run yet at this point,
so `hx-on:` still needs it. This stays report-only, so nothing can
break in production: browsers only report violations. Update the
policy's leading comment (`settings.py:307-311`) to describe the new
state.

**Verify**: `mise run test:py` will now fail the existing assertion
`"script-src 'self' 'unsafe-inline' 'unsafe-eval'" in header` in
`test_security_headers.py` — that is expected; fix it in Step 5, not
here. Confirm the failure is exactly that one assertion (`.venv/bin/pytest
tests/integration/web/test_security_headers.py -x` → 1 failure, the
`script-src` line) before continuing.

### Step 4: Eliminate `hx-on:` and drop `'unsafe-eval'`

For each of the 11 `hx-on:` sites (`components/checkbox-field.html:20`,
`panel/parts/timetable-session-detail.html:63,73`,
`panel/base.html:134,150,164,195,241,280,307,333`), replace the
inline JS with an equivalent same-origin mechanism that needs no
`'unsafe-eval'`:

- Prefer a small nonce-carrying `<script nonce="{{ csp_nonce }}">`
  block placed right after the element, using
  `document.currentScript.previousElementSibling.addEventListener(...)`,
  OR give the element a stable `id`/data attribute and attach the
  listener from a Vite module already loaded on that page (e.g.
  `panel/base.html` already loads page-level Vite assets — check
  `{% vite_asset %}` calls near the top of that file before adding a
  new one).
- Of the 8 `panel/base.html` sites, exactly 4 are byte-identical
  category-collapse toggles (`:195,241,280,307`, all
  `hx-on:click="var c=this.closest('[data-cat]')..."`) — those 4 are
  a good candidate for **one** shared `addEventListener` on a common
  ancestor (event delegation) rather than 4 separate listeners. The
  other 4 (`:134,150,164,333`) have distinct bodies and each needs
  its own conversion — do not skip them because of the delegation
  shortcut; all 8 must be eliminated. Use your judgment but keep the
  observable behavior (same classes toggled, same localStorage keys)
  identical.
- `components/checkbox-field.html:20`'s `hx_on_change` parameter is
  used by exactly one caller
  (`multiverse/panel/connections/edit.html:31`); after conversion,
  remove the `hx_on_change` parameter from the component and its one
  call site (grep `hx_on_change` to confirm no other caller exists
  before deleting).
- `panel/parts/timetable-session-detail.html:63,73`'s
  `hx-on::after-request` needs the htmx `htmx:afterRequest` event —
  attach via `addEventListener('htmx:afterRequest', ...)` on the
  element instead, checking `event.detail.successful` the same way.

Once all 11 sites are converted, remove `CSP.UNSAFE_EVAL` from
`script-src` in `CSP_REPORT_ONLY_POLICY`
(`src/ludamus/edges/settings.py`), leaving:

```python
"script-src": [CSP.SELF, CSP.NONCE],
```

**Verify**: `grep -rn "hx-on" src/ludamus/templates/` → no matches.
`mise run test:py` → all pass (any behavior test covering sidebar
toggle / category collapse / connection-edit checkbox / timetable
pane refresh must still pass unmodified — if none exist, that is a
pre-existing gap; do not add new tests for it in this plan unless a
step you touched previously had covering tests that now fail).

### Step 5: Update and extend `test_security_headers.py`

In `tests/integration/web/test_security_headers.py`:

- Update `test_header_sent_when_production_policy_active`'s
  `script-src` assertion to the new value:
  `assert "script-src 'self' 'nonce-" in header` (the nonce itself is
  random per request, so assert the stable prefix, not an exact
  string).
- Add a case asserting the nonce is present and non-empty, and that
  the same nonce value appears both in the response header and were
  it rendered in a template — model this as: render a page with at
  least one inline script (e.g. `reverse("web:index")` redirects, so
  use a page that actually renders `base.html`, such as
  `reverse("web:events")`), assert the response body contains
  `nonce="` and that a `'nonce-<value>'` token in the
  `Content-Security-Policy-Report-Only` header matches the value in
  the body via a regex extracting both.
- Keep `test_no_csp_headers_by_default` unmodified — it is the
  regression guard from plan 007.

**Verify**: `.venv/bin/pytest
tests/integration/web/test_security_headers.py` → all pass, including
the new nonce-match test.

### Step 6: Full gate for Step Groups A and B

**Verify**: `mise run check` → exit 0 (black, djlint, ruff, mypy
strict, import-linter, vulture, pylint, tingle). `mise run test:py` →
all pass. `grep -rn "hx-on" src/ludamus/templates/` → no matches.
`grep -n "UNSAFE_EVAL\|UNSAFE_INLINE" src/ludamus/edges/settings.py`
→ no matches in `CSP_REPORT_ONLY_POLICY`'s `script-src` line (style-src
keeps `CSP.UNSAFE_INLINE` — inline `style="..."` attributes are
explicitly out of scope for this plan; narrowing them is a separate,
larger effort not covered here).

### Step 7 (GATED — do not run without maintainer sign-off): report

destination decision note and enforcement flip

**STOP: do not perform this step unless the maintainer has reviewed
production report-only violation data and explicitly told you to
proceed.** See STOP conditions below. If you reach this point in a
normal execution pass with no such sign-off, stop after Step 6, report
that Steps 1-6 are done, and leave this step and its Done-criteria
items unchecked.

If and only if authorized, this step has two parts:

1. Add a short decision note as a comment above
   `CSP_REPORT_ONLY_POLICY` in `settings.py` recording where CSP
   violation reports are ingested (a `report-uri`/`report-to`
   directive value, or "none — reviewed via browser devtools/a
   specific log source" if the maintainer decided not to wire an
   endpoint). Do not add a new Django view or third-party dependency
   for this without separate, explicit instruction — that is its own
   scoped follow-up per plan 007's Maintenance notes.
2. Rename the production assignment from `SECURE_CSP_REPORT_ONLY` to
   `SECURE_CSP` (or set both during a transition window, if the
   maintainer asked for staged rollout) and update
   `test_security_headers.py` accordingly (`ENFORCE_HEADER` now
   expected, `REPORT_ONLY_HEADER` no longer sent — mirror the
   structure of the existing tests).

**Verify**: `mise run test:py` and `mise run check` → both pass.

## Test plan

- `test_security_headers.py::test_header_sent_when_production_policy_active`
  (updated) — the report-only header's `script-src` carries a nonce
  token, not `'unsafe-inline'`.
- `test_security_headers.py` new nonce-match test — the nonce value in
  the rendered page's `nonce="..."` attribute matches the
  `'nonce-...'` token in the CSP header for the same response.
- `test_security_headers.py::test_no_csp_headers_by_default` —
  unchanged regression guard.
- Any existing behavior test covering sidebar fold/collapse, the
  connections-edit checkbox, or the timetable detail pane refresh
  must still pass after Step 4's `hx-on:` conversions (find them via
  `grep -rl "sidebar\|panel-cat-\|connections/edit\|timetable-session-detail"
  tests/integration/web/` before starting Step 4, so you know what to
  re-run).
- Verification: `mise run test:py` → all pass, including the updated
  and new cases in `test_security_headers.py`.

## Done criteria

Machine-checkable. ALL must hold for Step Groups A and B (Steps 1-6):

- [ ] `grep -n "django.template.context_processors.csp"
  src/ludamus/edges/settings.py` returns exactly one match
- [ ] `grep -c 'nonce="{{ csp_nonce }}"' src/ludamus/templates/base.html
  src/ludamus/templates/components/theme_script.html
  src/ludamus/templates/panel/base.html` matches the counts from
  Step 2's Verify (accounting for the `500_dynamic.html` exception if
  applicable)
- [ ] `grep -rn "hx-on" src/ludamus/templates/` returns no matches
- [ ] `grep -n "CSP.UNSAFE_EVAL\|CSP.UNSAFE_INLINE"
  src/ludamus/edges/settings.py` shows `CSP.UNSAFE_INLINE` only on the
  `style-src` line, and no `CSP.UNSAFE_EVAL` anywhere
- [ ] `grep -cn "SECURE_CSP =" src/ludamus/edges/settings.py` returns
  0 (still no enforcing policy — Step 7 is gated)
- [ ] `mise run test:py` exits 0
- [ ] `mise run check` exits 0
- [ ] No `noqa` / `type: ignore` added anywhere (`git diff` review)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

Additional criteria for Step 7, ONLY if explicitly authorized and
executed:

- [ ] `grep -n "SECURE_CSP =" src/ludamus/edges/settings.py` returns
  exactly one match, inside `if IS_PRODUCTION:`
- [ ] `test_security_headers.py` asserts the enforcing header is sent

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts in "Current state" no longer match the live code
  (drift — e.g. a script site was added/removed/moved, or the
  `hx-on:` sites changed).
- **No production report-only violation data has been reviewed by the
  maintainer.** This is the default state as of this plan's writing.
  Step 7 (the `report-uri`/`report-to` decision and the `SECURE_CSP`
  enforcement flip) must NOT run under this condition — do Steps 1-6
  only, then stop and report Steps 1-6 complete. Do not infer
  authorization from anything in this plan file itself; it must come
  from the maintainer directly in your task instructions for this run.
- Removing `'unsafe-inline'` from `script-src` in Step 3 and running
  the app manually (or a smoke test) surfaces an inline script this
  plan's grep missed (e.g. one generated dynamically by a Django form
  widget rather than a static template). Report the exact
  file/line/widget rather than adding a broad `'unsafe-inline'`
  fallback back in.
- Converting an `hx-on:` site in Step 4 changes observable behavior in
  any existing test (a fix that would require touching a file outside
  the in-scope list).
- `mise run check` failures (mypy, vulture, pylint, tingle) that you
  cannot resolve within the in-scope files without adding a
  suppression directive.
- `500_dynamic.html`'s nonce turns out unavailable (error-handling
  path bypasses the CSP middleware) — leave that one file's script on
  a documented `'unsafe-inline'` carve-out (see Maintenance notes) and
  report it; do not force a nonce onto a request context that does
  not have one.

## Maintenance notes

- This plan deliberately stops short of enforcement. The order after
  this lands: (1) wire a report destination if the maintainer wants
  one, (2) let report-only data accumulate against the now-nonce-only
  `script-src`, (3) review it, (4) execute Step 7.
- If `500_dynamic.html` ends up with a residual `'unsafe-inline'`
  carve-out (see STOP conditions), that is a narrower, documented
  exception, not a reason to keep `'unsafe-inline'` policy-wide —
  record it as a one-line comment above `CSP_REPORT_ONLY_POLICY`
  pointing at the file.
- `style-src` keeps `'unsafe-inline'` after this plan — inline
  `style="..."` attributes are widespread (plan 007's recon:
  10+ files) and nonce-ifying attributes (as opposed to `<style>`
  blocks) is not supported by the CSP spec the same way; that is a
  separate, larger effort (likely: move inline styles to CSS classes)
  deliberately not scoped here.
- `img-src https:` stays broad — narrowing it to the concrete
  gravatar/Auth0/GCS hosts needs the same production-data review
  gating Step 7; consider bundling that into whatever change performs
  Step 7.
- If a new inline `<script>` or `hx-on:` attribute is added to a
  template after this lands, it must carry `nonce="{{ csp_nonce }}"`
  (script) or be converted to a real listener (hx-on) in the same PR
  — otherwise it silently relies on the report-only leniency and will
  break the moment Step 7 flips to enforcement.
- Reviewers should scrutinize: every nonce'd `<script>` tag actually
  renders inside a context that has the `csp` context processor
  (i.e., not a template rendered outside the normal Django template
  engine, like a plain-text email); and that the `hx-on:` conversions
  preserve exact behavior (category toggle state, localStorage keys,
  aria attributes) since these are UI-affecting changes with no
  dedicated behavior tests found during planning.
