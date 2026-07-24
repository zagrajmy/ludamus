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
>   src/ludamus/client/vite.config.ts \
>   tests/integration/web/test_security_headers.py
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

> **Executed in full, including the gated Step 8.** The maintainer
> authorized the enforcement flip in this plan's own PR (#583) rather
> than staging it behind separate report-only production data — see
> that PR's description for the rationale. `SECURE_CSP` is set in
> production, `CSP_REPORT_ONLY_POLICY` was renamed to `CSP_POLICY`,
> and `style-src` tightening was deliberately deferred (see "Deferred
> / next step" below). The STOP conditions, Done criteria, and Step
> 6-8 text below describe the plan **as originally written, before
> that authorization** — read them as history, not as a live gate on
> future work against this branch.

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
    execution time (Step 6's verify) that `request._csp_nonce` is
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
  without first converting all 11 sites to delegated `data-action`
  handlers in a Vite TS module — the concrete design in Step 4. NOT
  inline `<script>` tags and NOT `onclick=`-style attributes: both
  are tingle-penalized (see next bullet).
- **Frontend constraints and wiring facts** (all verified):
  - `tingle.toml:184-188` defines the `script-tags` metric (counts
    `<script` in templates) and `tingle.toml:221-225` defines
    `inline-handlers` (counts the regex
    `\son(click|change|submit|input|load)=` in templates).
    `tingle check` runs inside `mise run check` and fails when a
    branch grows these on net — so the `hx-on:`
    replacement must be a TS module with delegated listeners, not new
    inline `<script>` blocks or `onclick=` attributes.
  - Client TS modules live in `src/ludamus/client/src/`. Each module
    is (a) registered as a rollup input in
    `src/ludamus/client/vite.config.ts` under
    `build.rollupOptions.input` (e.g.
    `"tab-scroll": resolve(rootDir, "src/tab-scroll.ts")`) and
    (b) loaded by a template via django-vite, e.g. `base.html:56-61`:

    ```django
    {% vite_asset 'src/menu.ts' %}
    {% vite_asset 'src/tab-scroll.ts' %}
    ```

    `panel/base.html:382` already loads
    `{% vite_asset 'src/info-popover.ts' %}` — the new module is
    added next to it.
  - Delegated-listener exemplar: `src/ludamus/client/src/copy.ts` —
    one document-level click listener resolves
    `(e.target as Element | null)?.closest<HTMLElement>("[data-copy]")`
    and keeps every copy button declarative markup. Model the new
    module on it.
  - htmx access from TS: `src/ludamus/client/src/timetable.ts:21`
    declares `declare const htmx: { ajax(...): void; ... }` and at
    `:242` calls
    `htmx.ajax("GET", placement.backUrl, { swap: "outerHTML",
    target: "#left-pane" })` — the exact call shape Step 4 needs.
    Reuse that declaration pattern.
  - The vendored htmx is 2.0.8
    (`src/ludamus/static/vendor/htmx.min.js`, `version:"2.0.8"` in
    the bundle) and supports both the `allowEval` config flag and
    the `htmx-config` meta tag (both strings verified present in
    the bundle). htmx is loaded at `base.html:135` via
    `<script src="{% static 'vendor/htmx.min.js' %}"></script>`.
  - e2e coverage gap: `tests/e2e/tests/panel.spec.ts:106`
    ("opens panel dashboard with sidebar and stats") asserts the
    sidebar and `#eventSelector` are **visible** but no e2e test
    clicks the sidebar toggle, fold button, or category-collapse
    buttons — the panel-chrome behaviors converted in Step 4 have
    no automated behavioral coverage. See Step 4's Verify and the
    STOP conditions for the manual-QA requirement.
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
| Client TS lint | `mise run lint-client` | exit 0 |
| Markdown lint | `mise exec -- markdownlint-cli2 "plans/*.md"` | 0 errors |

## Suggested executor toolkit

- `product-design` skill — not needed for Step Groups A/B (no visible
  UI change, only attribute plumbing); do not invoke it for this plan.
- `docs/agents/architecture.md` — background on the GLIMPSE layers if
  any step turns up an unexpected import-linter violation (unlikely;
  this plan only touches `edges/settings.py`, templates, client TS,
  and tests).

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
- `src/ludamus/client/src/panel-chrome.ts` (create — see Step 4)
- `src/ludamus/client/vite.config.ts` (register the new module as a
  rollup input)
- `tests/integration/web/test_security_headers.py`

**Out of scope** (do NOT touch, even though they look related):

- Setting `SECURE_CSP` (the enforcing header) — Step Group C is
  GATED; see STOP conditions. Do not flip enforcement in this pass.
  _(As executed: the maintainer lifted this gate for PR #583 — see
  the "Status" note above. This scope list describes the plan as
  originally authored.)_
- A `report-uri` / `report-to` ingestion endpoint or third-party
  collector — Step Group C only writes the **decision note**; wiring
  an endpoint is a separate, human-scoped follow-up (plan 007's
  Maintenance notes already flagged this as deferred).
- Narrowing `img-src https:` to concrete hosts — that requires
  reviewing production report-only data too; out of scope here.
- Any behavior change to the scripts themselves beyond adding a
  `nonce` attribute (Group A) or converting `hx-on:` bodies into
  delegated `data-action` handlers with identical logic (Group B).
  No refactors, no new features.
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
`test_security_headers.py` — that is expected; fix it in Step 6, not
here. Confirm the failure is exactly that one assertion (`.venv/bin/pytest
tests/integration/web/test_security_headers.py -x` → 1 failure, the
`script-src` line) before continuing.

### Step 4: Create `panel-chrome.ts`, convert all 11 `hx-on:` sites

Create `src/ludamus/client/src/panel-chrome.ts`. It installs
**delegated document-level listeners keyed on `data-action`
attributes** — NOT inline `<script>` tags and NOT `onclick=`-style
attributes (the tingle ratchet penalizes both: `script-tags` and
`inline-handlers` metrics; see "Current state"). Model the delegation
on `src/ludamus/client/src/copy.ts`.

Wire it up (both parts required):

1. Register the rollup input in `src/ludamus/client/vite.config.ts`,
   alphabetically inside `build.rollupOptions.input`:

   ```ts
   "panel-chrome": resolve(rootDir, "src/panel-chrome.ts"),
   ```

2. Load it in `src/ludamus/templates/panel/base.html` next to the
   existing `{% vite_asset 'src/info-popover.ts' %}` (line 382):

   ```django
   {% vite_asset 'src/panel-chrome.ts' %}
   ```

   `multiverse/panel/connections/edit.html` extends
   `panel/base.html`, so it is covered;
   `panel/parts/timetable-session-detail.html` is an htmx partial
   swapped into panel pages, so document-level delegation needs no
   re-initialization after swaps.

Module shape (delegated dispatch; keep lines within the client's
lint rules — `mise run lint-client` gates it):

```ts
declare const htmx: {
  ajax(
    verb: string,
    url: string,
    options: { swap: string; target: string },
  ): void;
};

document.addEventListener("click", (e) => {
  const el = (e.target as Element | null)?.closest<HTMLElement>(
    "[data-action]",
  );
  // dispatch on el?.dataset.action: toggle-sidebar, toggle-fold,
  // toggle-category
});

document.addEventListener("change", (e) => {
  // dispatch on data-action: switch-event, sync-expanded-required
});

document.body.addEventListener("htmx:afterRequest", (e) => {
  // shared refresh-after-request handler, see conversion (e)
});
```

Per-site conversions (all bodies below quoted from the live
templates — re-verify each before editing):

- **(a) Sidebar toggles — `panel/base.html:134` and `:333` →
  `data-action="toggle-sidebar"` on both, ONE handler, no variant
  attribute.** The two bodies look different but are equivalent:

  ```text
  :134  document.getElementById('sidebar').classList
          .toggle('-translate-x-full'); this.classList
          .toggle('hidden')
  :333  document.getElementById('sidebar').classList
          .toggle('-translate-x-full'); document
          .getElementById('sidebarOverlay').classList
          .toggle('hidden')
  ```

  At `:134` the element carrying the handler IS `#sidebarOverlay`
  (the overlay button, id at `panel/base.html:132`), so
  `this.classList.toggle('hidden')` toggles the overlay — the same
  operation `:333` spells out by id. One handler covers both:

  ```ts
  const toggleSidebar = (): void => {
    document
      .getElementById("sidebar")
      ?.classList.toggle("-translate-x-full");
    document
      .getElementById("sidebarOverlay")
      ?.classList.toggle("hidden");
  };
  ```

- **(b) Fold toggle — `panel/base.html:150` →
  `data-action="toggle-fold"`.** Current body:

  ```text
  var h=document.documentElement;
  var f=h.toggleAttribute('data-folded');
  try{localStorage.setItem('panel-sidebar-folded',f?'1':'0');}
  catch(e){}
  ```

  Handler: `toggleAttribute("data-folded")` on `documentElement`,
  persist under the exact key `panel-sidebar-folded` (`"1"`/`"0"`),
  keep the try/catch (storage may be unavailable).

- **(c) Event switcher — `panel/base.html:164` →
  `data-action="switch-event"`, handled on `change`.** Current body:
  `window.location.href = '/panel/event/' + this.value + '/'`.
  Keep the URL construction server-side: each `<option>` (the
  `{% for event in events %}` loop right below `:164`) gains

  ```django
  data-url="{% url 'panel:event-index' slug=event.slug %}"
  ```

  (`panel:event-index` is the named route for `/panel/event/<slug>/`
  — `src/ludamus/gates/web/django/chronology/panel/urls.py:104`; the
  same name is already used at `panel/base.html:185`.) The handler
  reads the selected option's URL, never concatenates paths:

  ```ts
  const switchEvent = (select: HTMLSelectElement): void => {
    const url = select.selectedOptions[0]?.dataset.url;
    if (url) window.location.assign(url);
  };
  ```

- **(d) Category toggles — `panel/base.html:195,241,280,307`
  (byte-identical) → `data-action="toggle-category"` on each
  button.** Current body (x4):

  ```text
  var c=this.closest('[data-cat]').dataset.cat;
  var v=document.documentElement.classList.toggle('catc-'+c);
  try{localStorage.setItem('panel-cat-'+c,v?'1':'0');}catch(e){}
  ```

  One handler reads `el.closest("[data-cat]")?.dataset.cat`,
  toggles the `catc-${cat}` class on `documentElement`, persists
  under the exact key `panel-cat-${cat}` (`"1"`/`"0"`), try/catch
  kept.

- **(e) Timetable refresh-after-request —
  `panel/parts/timetable-session-detail.html:63` and `:73`.**
  Current attributes (quoted):

  ```text
  :63  hx-on::after-request="if(event.detail.successful){
         htmx.ajax('GET','{{ back_url }}',
         {target:'#left-pane',swap:'outerHTML'})}"
  :73  hx-on::after-request="if(event.detail.successful){
         htmx.ajax('GET','{{ detail_url }}',
         {target:'#left-pane',swap:'outerHTML'})}"
  ```

  Replace each `hx-on::after-request="..."` with two data
  attributes on the same `<form>`:

  ```django
  data-refresh-url="{{ back_url }}"
  data-refresh-target="#left-pane"
  ```

  (`{{ detail_url }}` at `:73`.) ONE shared listener in
  `panel-chrome.ts` replaces both:

  ```ts
  document.body.addEventListener("htmx:afterRequest", (e) => {
    const evt = e as CustomEvent<{ successful?: boolean }>;
    const el = (e.target as Element | null)?.closest<HTMLElement>(
      "[data-refresh-url]",
    );
    if (!el || !evt.detail.successful) return;
    const url = el.dataset.refreshUrl;
    const target = el.dataset.refreshTarget;
    if (!url || !target) return;
    htmx.ajax("GET", url, { swap: "outerHTML", target });
  });
  ```

  Same verb, URL, target, and swap as today; fires only on
  `event.detail.successful`, exactly like the current bodies.

- **(f) Checkbox component — `components/checkbox-field.html:20` +
  sole caller `multiverse/panel/connections/edit.html:31`.** Remove
  the `hx_on_change` string parameter from the component API
  entirely (the attribute at `:20` AND its mention in the docs
  comment at `:3`); grep `hx_on_change` first to confirm
  `connections/edit.html:31` is still the only caller. The caller
  currently passes this JS string (quoted):

  ```text
  this.setAttribute('aria-expanded',
    this.checked ? 'true' : 'false');
  var s=document.getElementById('id_secret');
  if (s) { if (this.checked) {
    s.setAttribute('aria-required', 'true');
  } else { s.removeAttribute('aria-required'); } }
  ```

  Replace with two declarative component parameters rendering data
  attributes on the `<input>`:

  ```django
  {% if data_action|default:"" %}
    data-action="{{ data_action }}"
  {% endif %}
  {% if data_required_target|default:"" %}
    data-required-target="{{ data_required_target }}"
  {% endif %}
  ```

  (Single-line `{% if %}...{% endif %}` per attribute is the
  component's existing style — collapse each to one line in the
  template; they are shown wrapped here only for line length.)

  The caller passes `data_action="sync-expanded-required"
  data_required_target="id_secret"` instead of the JS string. The
  delegated `change` handler:

  ```ts
  const syncExpandedRequired = (box: HTMLInputElement): void => {
    box.setAttribute("aria-expanded", box.checked ? "true" : "false");
    const id = box.dataset.requiredTarget;
    const field = id ? document.getElementById(id) : null;
    if (!field) return;
    if (box.checked) field.setAttribute("aria-required", "true");
    else field.removeAttribute("aria-required");
  };
  ```

**Verify**:
`grep -rn "hx-on" src/ludamus/templates/` → no matches;
`grep -rn "hx_on_change" src/ludamus/templates/` → no matches;
`mise run lint-client` → exit 0;
`mise run test:py` → all pass.
Behavioral check: the converted behaviors (sidebar toggle, fold,
category collapse, event switcher, timetable refresh, secret
checkbox) have NO automated coverage (`tests/e2e/tests/panel.spec.ts`
only asserts visibility). With a server running, drive the panel with
`mise run shots` (wraps `aubx agent-browser`) — click each converted
control and screenshot before/after to confirm identical behavior. If
you cannot run a browser in your environment, you MUST say so in your
report and flag the six behaviors for maintainer QA — do not silently
skip this (see STOP conditions).

### Step 5: Disable htmx eval (capstone), then drop `'unsafe-eval'`

Only after Step 4's verify passes. Add the htmx config meta tag to
`src/ludamus/templates/base.html`'s `<head>`, next to the viewport
meta (line 10):

```django
<meta name="htmx-config" content='{"allowEval":false}'>
```

Mechanism decision — the meta tag, not a TS assignment, because: it
is declarative and read by htmx at init regardless of module load
order; it keeps working even if a Vite module fails to load; it adds
no `<script>` tag (tingle `script-tags` metric unchanged); and the
vendored htmx 2.0.8 supports it (verified in the bundle, see
"Current state"). With `allowEval` off, any leftover or future
`hx-on:` attribute (or other eval-dependent htmx feature) triggers
`htmx:evalDisallowedError` at use time — regressions fail fast in
development, BEFORE the CSP enforcement flip can break production.

Then remove `CSP.UNSAFE_EVAL` from `script-src` in
`CSP_REPORT_ONLY_POLICY` (`src/ludamus/edges/settings.py`), leaving:

```python
"script-src": [CSP.SELF, CSP.NONCE],
```

**Verify**:
`grep -n 'htmx-config' src/ludamus/templates/base.html` → 1 match;
`grep -c "UNSAFE_EVAL" src/ludamus/edges/settings.py` → 0;
`mise run test:py` → all pass.

### Step 6: Update and extend `test_security_headers.py`

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

### Step 7: Full gate for Step Groups A and B

**Verify**: `mise run check` → exit 0 (black, djlint, ruff, mypy
strict, import-linter, vulture, pylint, tingle — tingle's
`script-tags` and `inline-handlers` metrics must not have grown).
`mise run lint-client` → exit 0. `mise run test:py` → all pass.
`grep -rn "hx-on" src/ludamus/templates/` → no matches.
`grep -n "UNSAFE_EVAL\|UNSAFE_INLINE" src/ludamus/edges/settings.py`
→ no matches in `CSP_REPORT_ONLY_POLICY`'s `script-src` line (style-src
keeps `CSP.UNSAFE_INLINE` — inline `style="..."` attributes are
explicitly out of scope for this plan; narrowing them is a separate,
larger effort not covered here).

### Step 8 (GATED — do not run without maintainer sign-off): report

destination decision note and enforcement flip

**Executed in PR #583** — the maintainer explicitly authorized the
flip without a separate report-only production window (see "Status"
above); the decision-note part (a `report-uri`/`report-to` endpoint)
remains deferred, tracked in "Deferred / next step" below. The gate
text that follows describes the plan as originally authored.

**STOP: do not perform this step unless the maintainer has reviewed
production report-only violation data and explicitly told you to
proceed.** See STOP conditions below. If you reach this point in a
normal execution pass with no such sign-off, stop after Step 7, report
that Steps 1-7 are done, and leave this step and its Done-criteria
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
- The six converted panel-chrome behaviors have no automated
  behavioral coverage (planning-time finding — `panel.spec.ts` only
  asserts visibility): the manual browser check in Step 4's Verify is
  the behavioral test for this plan; its outcome (done, or flagged
  for maintainer QA) must appear in the executor's report.
- Verification: `mise run test:py` → all pass, including the updated
  and new cases in `test_security_headers.py`.

## Done criteria

Machine-checkable. ALL must hold for Step Groups A and B (Steps 1-7):

- [ ] `grep -n "django.template.context_processors.csp"
  src/ludamus/edges/settings.py` returns exactly one match
- [ ] `grep -c 'nonce="{{ csp_nonce }}"' src/ludamus/templates/base.html
  src/ludamus/templates/components/theme_script.html
  src/ludamus/templates/panel/base.html` matches the counts from
  Step 2's Verify (accounting for the `500_dynamic.html` exception if
  applicable)
- [ ] `grep -rn "hx-on" src/ludamus/templates/` returns no matches
- [ ] `grep -rn "hx_on_change" src/ludamus/templates/` returns no
  matches
- [ ] `grep -n 'htmx-config' src/ludamus/templates/base.html` returns
  exactly one match (the `allowEval:false` meta tag)
- [ ] `grep -n "CSP.UNSAFE_EVAL\|CSP.UNSAFE_INLINE"
  src/ludamus/edges/settings.py` shows `CSP.UNSAFE_INLINE` only on the
  `style-src` line, and no `CSP.UNSAFE_EVAL` anywhere
- [ ] `grep -cn "SECURE_CSP =" src/ludamus/edges/settings.py` returns
  0 (still no enforcing policy — Step 8 is gated). _As executed in
  PR #583, Step 8 was authorized, so this specific check no longer
  holds — see the additional Step 8 criteria below and the "Status"
  note at the top of this plan._
- [ ] `mise run test:py` exits 0
- [ ] `mise run check` exits 0
- [ ] `mise run lint-client` exits 0
- [ ] No `noqa` / `type: ignore` added anywhere (`git diff` review)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] The executor's report states the manual browser check's outcome
  (verified, or flagged for maintainer QA) for the six converted
  panel-chrome behaviors
- [ ] `plans/README.md` status row updated

Additional criteria for Step 8, ONLY if explicitly authorized and
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
  Step 8 (the `report-uri`/`report-to` decision and the `SECURE_CSP`
  enforcement flip) must NOT run under this condition — do Steps 1-7
  only, then stop and report Steps 1-7 complete. Do not infer
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
- A converted `hx-on:` site's live body differs from the quoted body
  in Step 4 (drift) — re-derive the handler from the live body only
  if the difference is trivial (whitespace); otherwise stop.
- You finished Step 4 without being able to run the manual browser
  check AND without flagging the six panel-chrome behaviors for
  maintainer QA in your report — that combination is not allowed;
  never report Step 4 done while both are missing.
- `mise run check` failures (mypy, vulture, pylint, tingle —
  including growth in `script-tags` / `inline-handlers`) or
  `mise run lint-client` failures that you cannot resolve within the
  in-scope files without adding a suppression directive.
- `500_dynamic.html`'s nonce turns out unavailable (error-handling
  path bypasses the CSP middleware) — leave that one file's script on
  a documented `'unsafe-inline'` carve-out (see Maintenance notes) and
  report it; do not force a nonce onto a request context that does
  not have one.

## Maintenance notes

- This plan deliberately stops short of enforcement. The order after
  this lands: (1) wire a report destination if the maintainer wants
  one, (2) let report-only data accumulate against the now-nonce-only
  `script-src`, (3) review it, (4) execute Step 8.
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
  gating Step 8; consider bundling that into whatever change performs
  Step 8.
- If a new inline `<script>` is added to a template after this lands,
  it must carry `nonce="{{ csp_nonce }}"` in the same PR. A new
  `hx-on:` attribute will throw `htmx:evalDisallowedError` at use
  time (the `allowEval:false` meta from Step 5) — convert it to a
  `data-action` handler in `panel-chrome.ts` (or a page-appropriate
  module) instead. Otherwise the change silently relies on the
  report-only leniency and will break the moment Step 8 flips to
  enforcement.
- Reviewers should scrutinize: every nonce'd `<script>` tag actually
  renders inside a context that has the `csp` context processor
  (i.e., not a template rendered outside the normal Django template
  engine, like a plain-text email); and that the `hx-on:` conversions
  preserve exact behavior (category toggle state, localStorage keys,
  aria attributes) since these are UI-affecting changes with no
  dedicated behavior tests found during planning.

## Deferred / next step: style-src tightening

This PR nonces every inline `<script>` and drops `'unsafe-inline'` from
`script-src` (Step 8's enforcement flip is executed). `style-src`
still keeps `'unsafe-inline'` — that is the remaining half of the same
problem, deliberately out of scope here, and the natural next plan:

- Inline `<style>` **blocks** can be nonce'd exactly the same way
  scripts were in this plan (cheap, same `csp_nonce` mechanism).
- Inline `style="..."` **attributes** are the actual blocker: CSP
  nonces apply to `<style>`/`<script>` _elements_, not to `style=`
  attributes on arbitrary elements — there is no
  `style="{{ csp_nonce }}" ..."` equivalent. Removing `'unsafe-inline'`
  from `style-src` requires either (a) `'unsafe-hashes'` plus a
  SHA-256 hash per distinct attribute value (brittle — any change to
  the value breaks the hash, and dynamic/per-record values multiply
  the hash list), or (b) removing the inline style attributes
  entirely: static ones move to Tailwind/utility classes, and dynamic
  ones (computed positions/sizes — the timetable grid, meter widths,
  cover-image background images) move to CSS custom properties set via
  a small nonce'd `<style>` block or plain `data-*` attributes read by
  static CSS/JS.
- Given plan 007's recon found inline `style="..."` in 10+ files and
  this plan's own e2e pass just showed how easy it is to miss a
  legitimate external source (the Google Fonts stylesheet — see
  `settings.CSP_POLICY`'s `style-src`/`font-src` comment), ship that
  follow-up report-only first, the same staged way this plan did for
  scripts: the dynamic-style long tail is wide enough that enforcing
  blind is likely to break something.
- The `report-uri`/`report-to` violation-ingestion endpoint is still
  deferred (see plan 007's Maintenance notes and the comment above
  `CSP_POLICY` in `settings.py`); wiring one would also make the
  style-src follow-up's report-only phase actually reviewable instead
  of relying on manual devtools checks.
