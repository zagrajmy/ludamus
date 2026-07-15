# Plan 007: Ship a Content-Security-Policy in report-only mode

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to
> the next step. If anything in the "STOP conditions" section occurs,
> stop and report — do not improvise. Your reviewer maintains
> `plans/README.md`; do not edit it.
>
> **Drift check (run first)**:
>
> ```sh
> git diff --stat 7ffe8ba..HEAD -- \
>   src/ludamus/edges/settings.py \
>   src/ludamus/gates/web/django/templatetags/markdown_tags.py \
>   src/ludamus/links/gravatar.py \
>   src/ludamus/templates/base.html
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `7ffe8ba`, 2026-07-10

## Why this matters

The production security block sets HSTS, nosniff, `X_FRAME_OPTIONS`,
and a referrer policy — but no Content-Security-Policy. User-authored
markdown reaches pages through `mark_safe` sinks (nh3-sanitized, but
sanitizers are a single layer), and the tessera templatetags carry a
dozen more `mark_safe` calls. CSP is the standard second layer: if a
sanitizer bug or template mistake ever lets script through, CSP stops
it from executing. Shipping in **report-only** mode adds the header
without any risk of breaking pages — browsers log violations instead
of blocking — and produces the evidence needed to enforce later.

## Current state

- `src/ludamus/edges/settings.py:306-348` — the `if IS_PRODUCTION:`
  security block. Excerpt:

  ```python
  # Security Settings for Production
  if IS_PRODUCTION:
      ...
      # Security Headers
      SECURE_CONTENT_TYPE_NOSNIFF = True
      X_FRAME_OPTIONS = "DENY"
      ...
      # Additional Security Settings
      SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
  ```

  No `SECURE_CSP` / `SECURE_CSP_REPORT_ONLY` anywhere in the file.
- `src/ludamus/edges/settings.py:122-137` — `MIDDLEWARE` starts with
  `django.middleware.security.SecurityMiddleware`, then
  `whitenoise.middleware.WhiteNoiseMiddleware`; no CSP middleware.
- This repo runs Django 6.0.6 (`poetry show django`), which ships
  native CSP support — verified in the venv at
  `.venv/lib/python3.14/site-packages/django/middleware/csp.py`:
  `ContentSecurityPolicyMiddleware` reads `settings.SECURE_CSP` and
  `settings.SECURE_CSP_REPORT_ONLY` per response and skips the header
  when the config dict is empty (the global default is `{}` for both).
  Directive constants live in `django.utils.csp.CSP` (a `StrEnum` with
  `SELF`, `UNSAFE_INLINE`, `UNSAFE_EVAL`, `NONE`, ...). No new
  dependency is needed.
- `src/ludamus/gates/web/django/templatetags/markdown_tags.py:9-13` —
  the user-content sink this plan defends in depth:

  ```python
  @register.filter
  def render_markdown(text: str) -> str:
      if not text:
          return ""
      return mark_safe(_render_markdown(text))  # noqa: S308
  ```

  (`_render_markdown` is `ludamus.mills.render_markdown`, which nh3-
  cleans with an allowlist — `src/ludamus/mills/legacy.py:80-86`.)
- Facts that shape the policy values (all verified at planning time):
  - Inline `<script>` blocks are widespread: the theme-init script at
    `src/ludamus/templates/base.html:43-55`,
    `templates/components/theme_script.html:1`,
    `templates/panel/base.html:15` and `:383`, and more. So
    `script-src` needs `'unsafe-inline'` for now.
  - `hx-on:` attributes exist (`templates/components/
    checkbox-field.html`, `templates/panel/base.html`,
    `templates/panel/parts/timetable-session-detail.html`); htmx
    evaluates these via `Function`, so `script-src` also needs
    `'unsafe-eval'` to be a realistic enforcement target.
  - htmx and popper are vendored same-origin
    (`templates/base.html:134` loads
    `{% static 'vendor/htmx.min.js' %}`; `VENDOR_DEPENDENCIES` in
    settings). Vite bundles are same-origin in production
    (`django_vite` `dev_mode` is off when `ENV == "production"`,
    `settings.py:510-518`; whitenoise serves `/static/`).
  - Inline `style="..."` attributes are all over the templates
    (`grep -rl 'style="' src/ludamus/templates` → 10+ files), so
    `style-src` needs `'unsafe-inline'`.
  - Images come from three off-origin sources: gravatar
    (`src/ludamus/links/gravatar.py:11` —
    `https://www.gravatar.com/avatar/...`), Auth0-provided
    `user.avatar_url` (arbitrary HTTPS hosts, rendered e.g. at
    `templates/crowd/user/avatar.html:29`), and GCS media when the
    `GS_*` vars are set (`settings.py:368-381`, bucket URLs on
    `storage.googleapis.com`). Hence `img-src` gets broad `https:`
    plus `data:` for now.
- Test patterns: integration tests live under `tests/integration/web/`
  and use the `client` fixture plus the pytest-django `settings`
  fixture for overrides (see
  `tests/integration/web/test_middlewares.py:64` —
  `settings.ENV = "development"`). An autouse `sphere` fixture
  (`tests/integration/conftest.py:370`) creates the root site, so a
  plain `client.get(reverse("web:index"))` renders a full page. Use
  `assert_response` from `tests/integration/utils.py` for status
  checks — never manual status asserts.
- Repo rules that apply: NEVER add `noqa` / `type: ignore` / pylint
  directives; mypy runs strict; functions with 3+ parameters take
  keyword-only args; avoid docstrings; new tests for `gates` /
  settings-served headers are **integration** tests.
- Environment notes: run `mise install`, `poetry install` first, and
  `export MISE_ENV=sandbox` before any mise command in this container.
  Bare `mise run` may resolve a global pytest; prefix test/check runs
  with `PATH="$(pwd)/.venv/bin:$PATH"`. The CI-style gate is
  `mise run check` (there is no `prcheck` task).

## Commands you will need

| Purpose | Command | Expected on success |
| --- | --- | --- |
| Install | `mise install && poetry install` | exit 0 |
| All Py tests | `mise run test:py` | all pass |
| Unit tests | `mise run test:unit` | all pass |
| CI-style checks | `mise run check` | exit 0 |
| One test file | `.venv/bin/pytest tests/integration/web/<file>` | all pass |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/edges/settings.py`
- `tests/integration/web/test_security_headers.py` (create)

**Out of scope** (do NOT touch, even though they look related):

- Any template — no nonce plumbing, no removal of inline scripts or
  `style=` attributes in this plan.
- `markdown_tags.py`, `mills/legacy.py`, the tessera templatetags —
  the sanitizer stays exactly as is.
- Flipping to an enforcing `SECURE_CSP` — explicitly a follow-up after
  report-only data has been reviewed by a human.
- Any CSP report-ingestion endpoint (`report-uri` / `report-to`) —
  deciding where reports go is a human decision; see Maintenance
  notes.
- Adding `django-csp` or any other dependency.

## Git workflow

- Commit style example:
  `feat(edges): ship Content-Security-Policy in report-only mode`.
- End the commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR.

## Steps

### Step 1: Confirm native CSP support in the installed Django

Run:

```sh
.venv/bin/python -c \
  "from django.middleware.csp import ContentSecurityPolicyMiddleware; \
from django.utils.csp import CSP; print(CSP.SELF)"
```

**Verify**: prints `'self'` and exits 0. If this import fails, see
STOP conditions — do not substitute a third-party package.

### Step 2: Install the CSP middleware unconditionally

In `src/ludamus/edges/settings.py`, insert into `MIDDLEWARE`
immediately after `"django.middleware.security.SecurityMiddleware"`
(currently line 123):

```python
"django.middleware.csp.ContentSecurityPolicyMiddleware",
```

This is safe in every environment: with the default empty
`SECURE_CSP` / `SECURE_CSP_REPORT_ONLY` dicts the middleware adds no
header, so dev and tests see no behavior change.

**Verify**: `mise run test:py` → all pass, same count as before.

### Step 3: Define the report-only policy, enable it in production

In `src/ludamus/edges/settings.py`, add near the top-level imports:

```python
from django.utils.csp import CSP
```

Then define the policy as a module-level constant placed just above
the `# Security Settings for Production` comment (line 305), so tests
can import it even though `ENV != "production"` at import time:

```python
# Content-Security-Policy, report-only for now. 'unsafe-inline' in
# script-src/style-src covers the inline theme-init/panel scripts and
# inline style attributes; 'unsafe-eval' covers htmx hx-on:
# attributes; img-src is broad because avatars come from arbitrary
# Auth0/gravatar HTTPS hosts and media from GCS.
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

Inside the existing `if IS_PRODUCTION:` block, next to
`SECURE_REFERRER_POLICY` (line 342), add:

```python
SECURE_CSP_REPORT_ONLY = CSP_REPORT_ONLY_POLICY
```

Do NOT set `SECURE_CSP` — the enforcing header must not be sent.

**Verify**: `mise run test:py` → all pass (the assignment is inside
the production-only block, so the test environment is unaffected).

### Step 4: Add the integration tests

Create `tests/integration/web/test_security_headers.py`. Model the
file layout after `tests/integration/web/test_index_page.py` (class
per view concern, `assert_response` for status). Cover:

```python
from http import HTTPStatus

from django.urls import reverse

from ludamus.edges.settings import CSP_REPORT_ONLY_POLICY
from tests.integration.utils import assert_response

REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only"
ENFORCE_HEADER = "Content-Security-Policy"


class TestCSPReportOnlyHeader:
    URL = reverse("web:index")

    def test_header_sent_when_production_policy_active(
        self, client, settings
    ):
        settings.SECURE_CSP_REPORT_ONLY = CSP_REPORT_ONLY_POLICY

        response = client.get(self.URL)

        assert_response(response, HTTPStatus.OK)
        header = response.headers[REPORT_ONLY_HEADER]
        assert "default-src 'self'" in header
        assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in header
        assert "img-src 'self' data: https:" in header
        assert "frame-ancestors 'none'" in header
        assert ENFORCE_HEADER not in response

    def test_no_csp_headers_by_default(self, client):
        response = client.get(self.URL)

        assert_response(response, HTTPStatus.OK)
        assert REPORT_ONLY_HEADER not in response
        assert ENFORCE_HEADER not in response
```

(`header not in response` uses `HttpResponse.__contains__`, which
matches exact header names, so the report-only header does not
satisfy the enforce-header check.)

**Verify**:
`.venv/bin/pytest tests/integration/web/test_security_headers.py`
→ 2 passed.

### Step 5: Full gate

**Verify**: `mise run check` → exit 0 (black, djlint, ruff, mypy
strict, import-linter, vulture, pylint) and `mise run test:py` → all
pass. If vulture flags `CSP_REPORT_ONLY_POLICY` as unused, the test
import in Step 4 is its live reference — re-check the import before
assuming a whitelist is needed, and see STOP conditions rather than
adding suppressions.

## Test plan

- `test_security_headers.py::test_header_sent_when_production_policy_active`
  — the production policy dict, once active, emits a report-only
  header carrying the key directives, and no enforcing header.
- `test_security_headers.py::test_no_csp_headers_by_default` — dev and
  test environments stay header-free (regression guard for the
  unconditional middleware from Step 2).
- The full suite guards that inserting the middleware changes no
  existing response.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "ContentSecurityPolicyMiddleware"
  src/ludamus/edges/settings.py` returns exactly one match, inside
  `MIDDLEWARE`
- [ ] `grep -n "SECURE_CSP_REPORT_ONLY" src/ludamus/edges/settings.py`
  returns exactly one match, inside the `if IS_PRODUCTION:` block
- [ ] `grep -cn "SECURE_CSP =" src/ludamus/edges/settings.py`
  returns 0 (no enforcing policy)
- [ ] `mise run test:py` exits 0, including the 2 new tests
- [ ] `mise run check` exits 0
- [ ] No `noqa` / `type: ignore` added anywhere (`git diff` review)
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 fails: `django.middleware.csp` or `django.utils.csp` does not
  import — the installed Django lacks native CSP, and adding
  `django-csp` as a dependency is a human decision, not yours.
- The excerpts in "Current state" no longer match the live
  `settings.py` (drift — e.g. the security block moved or a CSP
  setting already exists).
- Inserting the middleware makes any existing test fail and the fix
  would require editing files outside the in-scope list.
- `mise run check` failures (mypy, vulture, pylint) that you cannot
  resolve within the in-scope files without adding a suppression
  directive.

## Maintenance notes

- This ships **report-only**. The deliberate follow-ups, in order:
  1. Add a report destination (`report-uri` / `report-to` directive
     plus an ingestion endpoint or third-party collector) so
     violations are visible outside browser devtools.
  2. After a quiet observation window, copy the policy to
     `SECURE_CSP` to enforce.
- Tightening path, once enforced: replace `'unsafe-inline'` in
  `script-src` with Django's CSP nonces (`CSP.NONCE` + the
  `csp_nonce` template variable) on the inline theme/panel scripts;
  drop `'unsafe-eval'` by replacing `hx-on:` attributes with vite
  modules; narrow `img-src https:` to the concrete avatar/media
  hosts once known from reports.
- Reviewers should scrutinize: the middleware is active in all
  environments while the policy is production-only (intended), and
  the enforcing `Content-Security-Policy` header is never emitted.
- If a template gains a third-party `<script src>` or external font,
  the policy constant must gain that origin — grep
  `CSP_REPORT_ONLY_POLICY` and update it in the same PR.
