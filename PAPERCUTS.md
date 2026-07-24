# Papercuts

Small friction hit while working — retried tool calls, confusing setup steps,
flaky commands, stale caches, misleading errors, non-obvious gotchas. One or two
sentences each: what you were doing → what got in the way.

If you fix a papercut, remove it.

<!-- Append new entries below, newest last. -->

- 2026-07-10: session-start hook's `playwright install --with-deps` fails in
  fresh sandboxes: apt-get update exits 100 because the image's ondrej/php PPA
  changed its InRelease Label. Browsers are preinstalled at /opt/pw-browsers so
  the failure is soft, but the WARN is misleading.
- 2026-07-10: `mise run papercut -- <note>` garbles apostrophes in the note
  (writes literal `'\''` sequences into PAPERCUTS.md) and doesn't wrap at 80
  columns, so the very next commit trips markdownlint MD013 on the file it
  just wrote. Fixed: the task now shlex-unquotes the note and wraps entries
  at 80 columns.
- 2026-07-10: fresh sandbox: `mise run check` failed with actionlint/hadolint
  not found. The image pre-bakes GitHub-layout installs of aliased tools; mise
  then skips installing them but cannot list their bin paths, so no shims and
  no task PATH entries. Fixed by purging installs without shims and rerunning
  `mise install` in the session-start hook.
- 2026-07-10: the pre-baked /opt/pw-browsers chromium build (1194) does not
  match @playwright/test 1.58.2 (needs 1208), so e2e cannot launch a browser
  and the preinstalled-browsers fallback is not real. Plain
  `playwright install` without `--with-deps` works through the proxy.
- 2026-07-13: aube install via mise fails for ~7 days after a release: ~/.npmrc
  min-release-age=7 blocks the darwin-arm64 platform package; one-shot fix
  npm_config_min_release_age=0 mise install npm:@endevco/aube
- 2026-07-13: dev DB root sphere domain drifted from ROOT_DOMAIN
  (localhost:8000) -> every request 500s with NotFoundError in
  middlewares.py:40; error page gives no hint which domain was looked up
- 2026-07-13: Ran 'mise run messages' to prune one msgid; makemessages scans
  worktrees/staging/ too, erroring on duplicate pot definitions and polluting
  django.po with combined-tree fuzzy entries. Had to stash the regen and hand-
  edit the .po.
- 2026-07-13: mise run messages-check false-passed ('Translations fresh') while
  vc-mtime warned 'failed to read git log output', then a rerun failed on a
  stale worktrees/issue-329 path in msguniq; third run gave the real result. The
  mtime cache seems to mask stale extraction.
- 2026-07-14: Tried to inspect gettext entries with polib, but the project
  environment does not install it; used the available gettext CLI instead.
- 2026-07-14: Passed focused pytest paths to mise run test:py, but the task
  appends them after its fixed integration/unit roots and runs the full suite;
  use -k for focused selection.
- 2026-07-14: Used a test_*party* zsh glob while locating party history tests;
  no match caused zsh to abort before rg. Use rg paths without shell globs.
- 2026-07-14: Passed a Playwright filename through mise run test:e2e; the task
  ignored it for Playwright, ran all 152 cases, then passed it to coverage
  report as Python source and failed after 148 passes/4 skips. The task should
  route test arguments only to Playwright.
- 2026-07-14: Tried `mise run pytest` for a focused test after `mise tasks`
  guidance; no such task exists, so focused pytest invocation still requires
  discovering another command.
- 2026-07-14: Catbox rejected PR screenshot uploads using the documented image-
  upload command with HTTP 412; the screenshot workflow needs a reliable host or
  required request headers documented.
- 2026-07-14: Built a screenshot asset commit, then zsh parsed
  `$asset_commit:refs/...` as a variable modifier and corrupted the push
  refspec; brace variables immediately before colons in zsh.
- 2026-07-14: Assumed fetched PR review-thread comments were objects with a body
  field; this repository helper returned a different shape and made the jq audit
  fail. Document the helper output schema or ship a ready unresolved-thread
  query.
- 2026-07-14: Used `mise exec -- pytest` to avoid the test:py task appending
  fixed roots, but it omitted required Varlock environment variables and failed
  before collection. Document a supported focused-Python-test command.
- 2026-07-14: Guessed the focused test belonged to TestSessionEnrollPage from
  its filename; pytest collected zero because the actual class is
  TestDesiredStateRouting. Locate node IDs before invoking focused tests.
- 2026-07-14: Ran a standalone Django metadata check after sourcing .env.test;
  DJANGO_SETTINGS_MODULE was still unset, so setup failed before printing the
  table name.
- 2026-07-14: Updating the PR body with gh pr edit failed on the deprecated
  Projects Classic GraphQL field; gh api with a PTY stdin payload also produced
  HTTP 400. A direct REST PATCH with a form field worked.
- 2026-07-14: Ran mise run fallow during PR review → task failed because the
  fallow binary is not installed; task output only suggests aube install.
- 2026-07-14: Running pytest directly to isolate coverage skipped mise test
  environment loading and failed because ENV was unset; source .env.test or
  provide a targeted mise task.
- 2026-07-14: Ran mise run check → taplo crashed in system-configuration
  dynamic_store before checks; check currently depends on a formatter that can
  fail from host configuration.
- 2026-07-14: Ran one targeted Playwright test; test:e2e always runs aube
  install, which retried registry requests despite existing node_modules and
  delayed local reproduction.
- 2026-07-14: Targeted Chromium could not launch after an accidentally
  unfiltered mise task spawned five browsers; stale Playwright Chromium
  processes hit macOS MachPortRendezvous bootstrap conflicts.
- 2026-07-14: A targeted event-card integration test exposed that Django strict
  missing-variable checks reject even an `{% if optional_var %}` guard; every
  include caller must pass the optional base explicitly.
- 2026-07-14: Ran lint:impeccable during validation → its detector produced no
  output for over three minutes and required interruption.
- 2026-07-14: Ran targeted pytest through mise exec to avoid the broad test
  task; it skipped varlock and failed because ENV was unset. Test tasks should
  support targeted paths without always prepending the whole suite.
- 2026-07-14: Ran test:postgres for the new party-invite concurrency check; the
  task assumes PostgreSQL is already running and all six marked tests failed at
  setup with connection refused.
- 2026-07-14: Ran poetry run pytest for focused party tests -> ENV was unset
  because only mise test tasks load .env.test; use the task or load its
  environment explicitly.
- 2026-07-23: Running mise tasks in the managed sandbox failed with Operation
  not permitted, so task discovery required a retry outside the sandbox.
- 2026-07-23: Running mise run test:int with focused files still prepended
  tests/integration, so a focused logout check unexpectedly ran the full
  2,298-test integration suite.
- 2026-07-23: Checking the seeded manager via user.spheres failed because
  Sphere.managers keeps Django's default reverse name; use user.sphere_set or
  query Sphere.managers directly.
- 2026-07-23: Ran a mixed JS/Python lint batch from src/ludamus/client while
  passing repository-root-relative paths; every path-based check failed. Run
  mixed checks from repo root or use paths relative to the chosen workdir.
- 2026-07-23: Formatting the Playwright test with aube exec -C tests/e2e failed
  because oxfmt is only available from the repository toolchain; running it from
  the repository root worked. format:djlint also exits nonzero after
  successfully reformatting a file, requiring a second pass.
- 2026-07-23: Running format:djlint for one navbar change reformatted an
  unrelated dirty template, then exited nonzero. A scoped formatter/check target
  would avoid disturbing concurrent work.
- 2026-07-23: Rebuilding frontend assets while the no-reload E2E server was
  running left Django's cached Vite manifest pointing at a deleted CSS file;
  browser tests rendered unstyled until the server was restarted.
- 2026-07-23: Ran mise tasks in the sandbox; mise failed with 'Operation not
  permitted' until retried with escalated permissions.
- 2026-07-23: Ran 'mise run test:int' with a path expecting a focused test; task
  appended the path after its hardcoded tests/integration target and launched
  the full suite instead.
- 2026-07-23: Concurrent UI work deleted a template while the E2E wrapper's
  post-test formatter scanned it, so a passing focused browser test reported
  task failure; rerun after agents settle.
- 2026-07-23: mise run format returns failure when djlint successfully reformats
  a file, requiring an identical second run to prove cleanliness.
- 2026-07-23: Focused Playwright runs silently found no tests when an auth spec
  was paired with the chromium project; use chromium-auth for *.auth.spec.ts.
- 2026-07-17: `mise run test:py -- some/path.py` silently runs the WHOLE suite:
  the task is 'pytest tests/integration tests/unit' so an appended path is an
  extra target, not a filter. Wasted two 5-minute full runs before noticing.
  Use -k instead, or make the task use a default arg.
- 2026-07-18: mise run test:py failed once with VariableDoesNotExist for
  danger_ring in TestEventImportLogPageView (navbar avatar include); full rerun
  passed - flaky, possibly test-order or faker-data dependent
- 2026-07-20: Ran mise run test:py with specific test paths after -- but the
  full suite ran anyway (paths are appended to the fixed targets, so they're an
  extra target rather than a filter); also test_import_views
  test_get_groups_errors_and_successes flaked once in a full run, passed on
  rerun
- 2026-07-22: mise run/exec in the web sandbox re-attempts installing missing
  tools (pipx:shellcheck-py, hadolint) and dies on pypi resolution before
  running the requested task, even with MISE_ENV=sandbox - this also blocks mise
  run papercut itself; worked around with scratchpad playwright-core + /opt/pw-
  browsers/chromium for screenshots and hand-appending this entry
- 2026-07-23: Wrapped validation commands used zsh reserved variable status, so
  result capture failed after the tasks completed; use a task-specific exit
  variable.
- 2026-07-24: Running a focused E2E via mise run test:e2e with an anchored
  suite/title grep matched zero tests; Playwright output did not reveal the
  actual full title. Retried with the unique test-name substring.
- 2026-07-24: The standalone tests/e2e npx tsc --noEmit check is red on four
  unrelated existing errors, so it cannot provide a clean focused-test signal.
  Playwright still transpiles and executes the changed spec successfully.
- 2026-07-24: test_event_page.py::test_query_count_constant_in_session_count
  flaked once under parallel run with 'UNIQUE constraint failed: sphere.site_id'
  — passed on re-run, looks like a test-isolation collision between sphere/site
  fixtures
