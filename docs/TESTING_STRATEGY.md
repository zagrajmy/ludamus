# Testing Strategy

## E2E first

- Never write unit tests after you write code. A test written from the code it
  checks restates that code: it always passes, catches almost nothing, and
  breaks on every refactor.
- Highly prefer E2E tests (Playwright, `tests/e2e`) as the sole testing
  mechanism. Use them to verify complex features work. At the end of an E2E
  test, produce a verifiable and repeatable artifact (a screenshot, a
  downloaded export, a printed PDF, a DB state dump) that a reviewer can check.
- If you must test a system in isolation, first write down all the ways it
  could fail, then write the code. Each failure mode becomes one test. A
  regression test that reproduces a bug before the fix is test-first too.

A unit test earns its place only when it would catch a real bug the E2E and
integration suites miss: tricky pure logic (time boundaries, capacity and
waitlist rules, permissions, secret scrubbing, parsers) or a repo-wide guard
(translation catalog, template checks, theme contrast). Tests that stub a
repository and assert the service passed arguments through, or that assert DTO
field mapping, constants, or template-tag wrappers, do not.

When a Python test is warranted, the layer decides its type: `gates`, `links`,
`adapters.web`, and templates get **integration** tests. Never raise coverage
with a mock-everything unit test of IO-bearing code: views, repositories,
importers.

## Helpers keep Arrange-Act-Assert visible

Repeated setup or repeated expected-value construction goes into a module-level
`_helper`, so each test stays three readable blocks. Extract when a block hides
which phase a test is in, or when Pylint's `R0801` flags the duplication. One
helper builds one thing, takes keyword-only arguments named after what varies,
branches never, and asserts nothing. What the test is about stays at the call
site: a helper that swallows the value under assertion trades duplication for a
test that no longer says what it checks. Helpers live in the test module that
owns them, or in a sibling `helpers.py` once a second module needs them — see
`tests/integration/web/chronology/helpers.py` and the `_timetable_document` /
`_one_hour_page` helpers in `test_event_print_page.py`.

## Unit tests

Cover: the isolated systems that meet the bar above, with one test per failure
mode written down before the code.

Rules:

- mock at highest level
- assert outcomes, not call sequences
- no database

## Integration tests

Cover: gates (views), links (public methods and functions).

Rules:

- mock at lowest level, or not at all — use test db, `responses`, or dedicated
  mock package
- assert outbound calls to external systems (the request is the contract);
  don't assert internal call sequences
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

Cover: every feature a user can reach, first. Playwright (TypeScript).

Verify **features work** in a real browser.

Scope: operations and workflows (create, edit, delete, filter, navigate).
Combine related actions per test (apply several filters at once; create then
edit).

Per-branch context coverage belongs in integration.

The run also measures the client TypeScript: Chromium's V8 coverage is
collected per test and mapped back through the bundle's inline sourcemaps to
`src/ludamus/client/src/*.ts`, landing in `coverage-client/lcov.info`. CI
uploads it to Codecov under the `client` flag, next to the Python report from
pytest and the same run's Django server.

Read that number as a **ceiling**. V8 reports only the scripts the browser
loaded, so a module no spec reaches is missing from the report entirely rather
than counted as uncovered — it leaves the denominator, and the percentage goes
up. Two more limits: coverage comes from the `page` a test is given, so a test
that opens its own context via `browser.newContext()` contributes nothing, and
only Chromium reports at all, so a behaviour covered exclusively by a
Firefox-only spec reads as uncovered.
