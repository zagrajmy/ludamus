# Plan 013: Remove the dead csrf_token field from OAuth state

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
>   src/ludamus/gates/web/django/crowd/auth.py \
>   tests/integration/web/crowd/test_auth0_login_action.py \
>   tests/integration/web/crowd/test_auth0_login_callback_action.py \
>   tests/integration/web/crowd/test_claim.py
> ```
>
> If any of those files changed since this plan was written, compare
> the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `7ffe8ba`, 2026-07-10

## Why this matters

The Auth0 login view stores a `csrf_token` in the cached OAuth state,
but the callback never reads it back — no code compares it to
anything. Dead security code is worse than no code: it implies a
check that does not exist, so a reader (or auditor) assumes the OAuth
flow is CSRF-bound to the browser session when it is not. Actual
protection is already provided twice over: the `state_token` is 32
random bytes, single-use (cache-deleted on first read), and authlib
validates the `state` parameter on token exchange. Deleting the field
makes the code tell the truth. The decision is **remove, not wire
up** — comparing a cookie snapshot would add nothing over the
existing single-use random token.

## Current state

- `src/ludamus/gates/web/django/crowd/auth.py:100-110` — the only
  write site, in `Auth0LoginActionView.get`:

  ```python
  # Generate a secure state token
  state_token = token_urlsafe(32)

  # Store state data in cache with 10 minute timeout
  state_data = {
      "redirect_to": next_path,
      "created_at": datetime.now(UTC).isoformat(),
      "csrf_token": request.META.get("CSRF_COOKIE", ""),
  }
  cache_key = f"oauth_state:{state_token}"
  cache.set(cache_key, json.dumps(state_data), timeout=CACHE_TIMEOUT)
  ```

- `src/ludamus/gates/web/django/crowd/auth.py:215-247` —
  `Auth0LoginCallbackActionView._resolve_oauth_state` is the only
  reader of the cached blob. It deletes the cache key (line 230,
  single-use), then reads only `redirect_to` (line 234) and
  `created_at` (line 236). It never touches `csrf_token`.
- All `csrf_token` occurrences in Python files at planning time
  (`grep -rn "csrf_token" src/ tests/ --include="*.py"`):
  - `src/ludamus/gates/web/django/crowd/auth.py:107` — the write site.
  - `tests/integration/web/crowd/test_auth0_login_action.py:32` —
    exact-dict assertion on the cached state (lines 29-33):

    ```python
    assert cached_data == {
        "redirect_to": None,
        "created_at": cached_data["created_at"],
        "csrf_token": "",
    }
    ```

  - `tests/integration/web/crowd/test_auth0_login_callback_action.py`
    `:25` (inside the `_setup_valid_state` helper, lines 19-27) and
    `:204` (inline `state_data` in `test_error_expired_state`) — both
    construct state blobs containing `"csrf_token": "test_csrf_token"`.
  - `tests/integration/web/crowd/test_claim.py:192` — the
    `_valid_state` helper (lines 183-197) builds the same blob.
- `{% csrf_token %}` occurrences in `src/ludamus/templates/*.html`
  are Django's form-CSRF template tag — completely unrelated; leave
  every template alone.
- Repo rules that apply: NEVER add `noqa` / `type: ignore` / pylint
  directives; mypy runs strict; avoid docstrings; these are
  integration tests (`gates` layer) — keep using the `client` fixture
  and `assert_response` from `tests/integration/utils.py`, and never
  loosen an exact-value assertion to `ANY` for simple values.
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
| One test file | `.venv/bin/pytest tests/integration/web/crowd/<file>` | all pass |

## Scope

**In scope** (the only files you should modify):

- `src/ludamus/gates/web/django/crowd/auth.py`
- `tests/integration/web/crowd/test_auth0_login_action.py`
- `tests/integration/web/crowd/test_auth0_login_callback_action.py`
- `tests/integration/web/crowd/test_claim.py`

**Out of scope** (do NOT touch, even though they look related):

- `_resolve_oauth_state` beyond leaving it exactly as is — no
  refactors, no new validation. Wiring up a cookie comparison is
  explicitly rejected, not deferred.
- The `state_token` generation, cache timeout, or authlib call.
- Templates containing `{% csrf_token %}` — Django form CSRF,
  unrelated.
- Django CSRF settings (`CSRF_COOKIE_*` in `edges/settings.py`).

## Git workflow

- Commit style example:
  `refactor(gates): drop dead csrf_token from oauth state`.
- End the commit message with
  `Co-authored-by: hasparus <hasparus@gmail.com>`.
- Do NOT push or open a PR.

## Steps

### Step 1: Confirm the field is dead

Run:

```sh
grep -rn "csrf_token" src/ tests/ --include="*.py"
```

**Verify**: the only hits are the five listed in "Current state"
(one write site in `auth.py`, four test constructions/assertions).
Any other Python hit — especially anything that reads
`state_data["csrf_token"]` or `.get("csrf_token")` — is a STOP
condition.

### Step 2: Delete the field at the write site

In `src/ludamus/gates/web/django/crowd/auth.py`, remove the line

```python
"csrf_token": request.META.get("CSRF_COOKIE", ""),
```

from the `state_data` dict (line 107), leaving `redirect_to` and
`created_at` untouched.

**Verify**:
`grep -n "csrf_token" src/ludamus/gates/web/django/crowd/auth.py`
→ no matches.

### Step 3: Update the tests that build or assert the state blob

- `tests/integration/web/crowd/test_auth0_login_action.py:29-33` —
  drop the `"csrf_token": "",` line from the exact-dict assertion so
  it becomes:

  ```python
  assert cached_data == {
      "redirect_to": None,
      "created_at": cached_data["created_at"],
  }
  ```

- `tests/integration/web/crowd/test_auth0_login_callback_action.py` —
  remove the `"csrf_token": "test_csrf_token",` line from
  `_setup_valid_state` (line 25) and from the inline `state_data` in
  `test_error_expired_state` (line 204).
- `tests/integration/web/crowd/test_claim.py` — remove the same line
  from the `_valid_state` helper (line 192).

Keep every other key and assertion byte-identical; do not restructure
the helpers.

**Verify**:

```sh
.venv/bin/pytest \
  tests/integration/web/crowd/test_auth0_login_action.py \
  tests/integration/web/crowd/test_auth0_login_callback_action.py \
  tests/integration/web/crowd/test_claim.py
```

→ all pass.

### Step 4: Full gate

**Verify**: `mise run test:py` → all pass, and `mise run check` →
exit 0 (black, djlint, ruff, mypy strict, import-linter, vulture,
pylint).

## Test plan

- No new tests: this deletes dead data, and the existing login,
  callback, expiry, and claim tests already pin the surviving
  behavior (`redirect_to` round-trip, `created_at` expiry check,
  single-use cache deletion).
- The updated exact-dict assertion in `test_auth0_login_action.py`
  is the regression guard: it fails if anyone re-adds a field to the
  cached state without a reader.
- Verification: `mise run test:py` → all pass, same test count as
  before (no tests added or removed, only edited).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -rn "csrf_token" src/ tests/ --include="*.py"` returns no
  matches
- [ ] `git diff 7ffe8ba..HEAD -- src/ludamus/templates` shows no
  template changes from this plan
- [ ] `mise run test:py` exits 0
- [ ] `mise run check` exits 0
- [ ] No files outside the in-scope list are modified (`git status`)

## STOP conditions

Stop and report back (do not improvise) if:

- Step 1 finds any reader of the field outside the write site — any
  Python hit beyond the five listed, or any access to
  `state_data["csrf_token"]` / `.get("csrf_token")` anywhere.
- The excerpts in "Current state" no longer match the live code
  (drift — e.g. `_resolve_oauth_state` gained a csrf comparison since
  planning; that would mean the field is no longer dead and this plan
  is obsolete).
- Any test failure after Step 3 that is not obviously the removed
  dict key — do not "fix" unrelated auth behavior to get green.

## Maintenance notes

- The OAuth CSRF story after this change, for reviewers: protection =
  random single-use `state_token` (32 bytes, `token_urlsafe`, cache
  key deleted on first use) + authlib's own `state` validation in
  `authorize_access_token`. Nothing was weakened — the deleted field
  was write-only.
- If someone later wants defense-in-depth binding the OAuth flow to
  the browser session, the right shape is comparing a value stored in
  the *session* (not the CSRF cookie snapshot) — a new design, not a
  revival of this field.
- Reviewers should scrutinize: the diff touches exactly one line in
  `auth.py` plus three test files, and no template.
