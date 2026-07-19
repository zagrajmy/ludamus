# Testing Strategy

## Layer determines test type

The layer of the code under test dictates the test type — **not** convenience,
and not what is easiest to reach for coverage:

- `mills` → **unit** tests (coverage: `test:unit:cov:diff`,
  `--cov=ludamus.mills`).
- `gates`, `links`, `adapters.web`, templates → **integration** tests
  (coverage: `test:int:cov:diff`).

This holds when chasing coverage too: an uncovered line is covered by the test
type that owns its layer. A missing line in `links` or `gates` means a missing
**integration** test, even when a quick mock-everything unit test would hit the
same line. Never raise `gates` / `links` / `adapters.web` coverage with a
mock-everything unit test of IO-bearing code — views, repositories, importers.

**Exception — pure helper functions.** A standalone function with **no IO** (no
DB, no HTTP, no `request` / `response`, no template rendering, no Django form or
model objects) may have a unit test wherever it lives, because there is nothing
to *integrate*. Template-tag filters like `clsx`, `format_duration`,
`render_markdown`, `avatar_bg_class`, and string helpers like `suggest_copy_name`
qualify. A test that renders a template (`Template(...).render(...)`) or builds
a form/widget is **not** pure — that is an integration test, regardless of which
file the helper lives in.

## Unit tests

Cover: mills (public methods and functions), plus pure IO-free helper functions
from any layer (see the exception above).

Rules:

- mock at highest level
- assert all mock calls
- no database

## Integration tests

Cover: gates (views), links (public methods and functions).

Rules:

- mock at lowest level, or not at all — use test db, `responses`, or dedicated
  mock package
- assert all mock calls
- assert all side effects

### Database fixtures

Default is `db` (autouse in `tests/integration/conftest.py`): wraps the test in
a transaction, rolls back. Nothing commits.

`transactional_db` (identical to `@pytest.mark.django_db(transaction=True)`)
does the opposite of its name: **no** wrapping transaction, writes really
commit, teardown truncates every table and re-emits `post_migrate`. Reach for
it only when the test asserts real transaction behavior:

- `transaction.on_commit()` callbacks — never fire under `db`
- `select_for_update()` row locking (also needs `@pytest.mark.postgres`)
- a second connection or thread must see the data (live server)
- asserting a failed `atomic()` block rolled back

Apply it to the whole test class, not one method — mark the class with
`@pytest.mark.usefixtures("transactional_db")` so a sibling test added later
inherits the transaction semantics its neighbours already rely on.

Cost is not only speed. The teardown flush deletes rows seeded by data
migrations (`0002_default_site`), then `post_migrate` re-creates whatever it
would create against an empty table. Later tests in the same run see a
different database than migrations built — `example.com` appears, the
`ROOT_DOMAIN` site vanishes. Tests that pass only because an earlier
transactional test flushed the table fail the moment they run first.

For `on_commit` prefer `django_capture_on_commit_callbacks(execute=True)` over
`transactional_db`: it runs the callbacks without real commits, keeping the
rollback path.

```python
with django_capture_on_commit_callbacks(execute=True):
    call_command("send_printables_reminders")

assert len(mailoutbox) == 1
```

Wrap **negative** assertions in it too. `assert mailoutbox == []` under `db`
passes unconditionally — the callback never ran, so the check cannot fail.

### Views and commands

Verify view→template **context contract**: views produce the right data for
every branch.

Structure: `{noun}/{page}/test_url_name.py` (existing directories keep
their legacy subdomain names until renamed)

Rules:

- use `assert_response`
- `ANY` only when objects are incomparable
- one test per meaningful context branch (empty vs populated, roles,
  permissions, edges)

Rendered-page behavior belongs in e2e.

### Links

Verify driven adapters against real infrastructure.

Structure: mimic code.

Skip (no test of any kind — do not "move" them to a unit test): one-liners,
conditional-free / error-free functions (thin SDK wrappers). A `links` module
with real logic (branching, error handling, parsing) is not a thin wrapper — it
gets an integration test, never a unit test.

## End-to-end tests

Cover: gates. Playwright (TypeScript).

Verify **features work** in a real browser.

Scope: operations and workflows (create, edit, delete, filter, navigate).
Combine related actions per test (apply several filters at once; create then
edit).

Per-branch context coverage belongs in integration.

## Migration to the new strategy

1. Move current integration tests to the right directories and files.
2. Drop tests that no longer fit. Move a test to unit tests **only** when it
   exercises `mills` logic; tests of `gates` / `links` stay integration.
3. Reach 100% component-test coverage.
4. Add e2e tests for current dynamic features.
