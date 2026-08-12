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
- 2026-07-23: mypy INTERNAL ERROR in django-stubs request.pyi during mise run
  check; deleting .mypy_cache fixed it
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
- 2026-07-24: Committed from a new git worktree → hook startup failed because
  the copied mise.toml was untrusted; trust was required before hooks could run.
- 2026-07-24: Used agent-browser find role link with an exact Log in name → it
  reported no element despite the snapshot listing matching links; clicking the
  snapshot ref worked.
- 2026-07-24: Created a fresh Playwriter session → the CLI returned an ID but
  immediately reported that session as missing; reused the user-authorized
  existing session and created a dedicated page there.
- 2026-07-24: Ran format:djlint on newly added templates → it reformatted them
  cleanly but still exited nonzero, requiring a second identical run.
- 2026-07-24: Passed focused test paths to mise run test:unit after -- → the
  task still ran the entire tests/unit suite instead of only those paths.
- 2026-07-24: Ran the documented messages task in a fresh worktree → varlock
  rejected missing development secrets instead of loading the repository test
  environment.
- 2026-07-24: Ran focused pytest directly without loading .env.test, so Django
  settings rejected the missing ENV variable; focused-test invocation depends on
  an easy-to-miss environment-loading step.
- 2026-07-24: Translation extraction previously run from the parent checkout
  embedded worktrees/prod-email-testing prefixes in every PO source reference,
  creating thousands of noisy changes and making messages-check fail when run
  from the worktree root.
- 2026-07-24: While carving enrollment views out of event_settings.py, removing
  a shared timezone import also broke pre-existing settings code; Ruff caught
  the cross-section import coupling before commit.
- 2026-07-24: Uploading required PR screenshots to Catbox returned HTTP 412 for
  every PNG, so the documented image-upload path could not publish the evidence.
- 2026-07-24: playwriter 'session new' printed a fresh id but the relay 404'd it
  (Session 14 not found); had to reuse an old session id from session list
- 2026-07-25: mise run papercut (and mise exec) in a web sandbox first tries to
  install pipx:shellcheck-py==0.11.0 and hadolint-py==2.14.0; uv can't find
  those versions on the first PyPI index and mise errors out, so the papercut
  task itself never runs. Appended by hand.
- 2026-07-25: Web sandbox session started with an empty .venv (no pytest, no
  django) and mise still wedged on pipx:shellcheck-py/hadolint-py, so no mise
  task could bootstrap it; ran poetry install by hand and invoked pytest as
  .venv/bin/python -m pytest with PYTHONPATH=src plus .env.test sourced
  manually.
- 2026-07-25: /opt/pw-browsers held chromium_headless_shell-1208 as an empty
  directory, so every e2e test failed with "Executable doesn't exist" until
  npx playwright install chromium refetched it.
- 2026-07-25: Iterated on timetable CSS/TS against a `.env.e2e` server, where
  `ENV="test"` turns django_vite `dev_mode` off, so each edit needed
  `aubr build` plus a restart (`--noreload` caches the manifest, and the
  rebuild deletes the hashed files it points at - the page then renders with
  no CSS and reads as a layout bug). For an edit loop against the e2e seed,
  export `ENV=development` and `VITE_PORT`, run the vite dev server, and keep
  the rest of `.env.e2e`: assets come from vite with HMR, no build, no
  restart. Build only before handing the page to Playwright.
- 2026-07-27: mise run check (format+lint) omits messages-check, so a stale PL
  catalog passes locally and only fails in CI; after any edit that reorders
  translated strings, run 'mise run messages-check' separately.
- 2026-07-28: Investigated login in the web sandbox: mise run start failed on
  varlock validation because the session's .env.local existed but was
  incomplete, and bootstrap's `if [ ! -f .env.local ]` guard never repairs an
  existing file; `rm .env.local && mise run bootstrap` regenerates it properly.
- 2026-07-28: auth0-simulator stays disabled in the sandbox until you hand-roll
  ~/.portless certs, and Python 3.14 rejects a bare self-signed CA without
  keyUsage=keyCertSign, so the first cert attempt failed with
  CERTIFICATE_VERIFY_FAILED.
- 2026-07-29: ran mise run shots -- '/event/x/print/?material=timetable' — task
  warned 'not reachable' although the server was up; $usage_targets keeps the
  shell quotes around each arg, so the URL becomes
  <http://localhost:8000'/event/>...'. Worked around by calling aubx agent-browser
  directly.
- 2026-07-29: rebuilt the vite client while test:e2e:serve was running —
  django_vite's cached manifest kept serving deleted hashed JS, pages silently
  lost their scripts until a manual server restart. Fixed test:e2e:serve to
  watch manifest.json and bounce itself.
- 2026-07-30: Web-sandbox image shipped without mise entirely; session-start.sh
  assumed the binary exists, so every provisioning step warned-and-skipped and
  the session looked half-provisioned. Installed it from mise.run (reachable
  through the proxy) and added a self-install step to the hook.
- 2026-07-31: every mise task resolves its Python tool from PATH, so any shell
  that puts ~/.local/bin ahead of the mise shims gets the image's uv-installed
  pytest/mypy/black instead of .venv's. 'mise run test:py' then dies with
  ModuleNotFoundError: No module named 'django'. Took a while to spot because
  the traceback points at tests/conftest.py, not at the wrong interpreter.
  session-start.sh orders PATH correctly; nothing enforces it elsewhere.
- 2026-08-01: mise run test:int -- tests/foo/test_x.py doesn't narrow: the task
  hardcodes the integration path and appends args, so pytest gets two paths and
  runs the whole suite. Had to use `-k name` and wait ~2.5 min for
  collection+run instead of 5s.
- 2026-08-01: git push over SSH fails with 'Bad owner or permissions on
  /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf' (symlink owned by
  nobody:nogroup); worked around with git -c credential.helper='!gh auth git-
  credential' push <https://github.com/zagrajmy/ludamus.git> HEAD:the-branch
- 2026-08-02: mise run shots fails on this machine: Chrome aborts with 'No
  usable sandbox' before writing DevToolsActivePort. Playwright (test:e2e)
  launches fine, so the wrapper needs --no-sandbox or a note pointing at the e2e
  screenshots instead.
- 2026-08-02: Firefox e2e project cannot launch on this machine: every firefox
  test dies with 'browserContext.newPage: Test timeout' during page setup, while
  chromium passes. Makes a full 'mise run test:e2e' unusable locally; had to run
  --project=chromium to get a signal.
- 2026-08-01: e2e: Firefox project fails locally with 'browserContext.newPage:
  Test timeout' on every spec (even untouched ones like sound.spec.ts); only
  chromium is runnable here, so a local full 'mise run test:e2e' always ends red
  and 63 tests report 'did not run'. Had to verify per-project.
- 2026-08-01: e2e: 'panel redirects to home with message when sphere has no
  events' (panel.spec.ts) fails locally on a freshly prepped DB even with no
  working-tree changes — /panel/ stays put instead of redirecting to /events/.
  It also aborts the rest of panel.spec.ts (serial mode), so 43 tests report
  'did not run'.
- 2026-08-02: Pre-commit oxlint hook fails with 'Cannot find module eslint-
  plugin-sonarjs'; the aube store entry node_modules/.aube/eslint-plugin-
  sonarjs@3.0.6_.../node_modules/eslint-plugin-sonarjs is extracted without a
  package.json (only cjs/docs/types), and 'aube install' reports 'already up to
  date' so it never repairs it. Blocks every commit touching a .ts file.
- 2026-08-01: mise run lint fails locally on lint:hk: oxlint can't build
  src/ludamus/client/oxlint.config.ts because eslint-plugin-sonarjs isn't
  installed in the local node_modules (CI is fine). Same failure on a clean
  tree, so it's env drift, not a code problem — had to stash and re-run to prove
  my change was innocent.
- 2026-08-02: mise run check → lint:vulture recursively scanned
  .claude/worktrees/*/.venv created by review agents, then failed on third-party
  packages instead of project code.
- 2026-08-02: mise run shots with a query-string URL → mise preserved literal
  shell quotes in usage_targets, so the generated URL contained apostrophes and
  curl rejected it; direct agent-browser worked.
- 2026-08-02: mise run test:e2e -- tests/print-flow.spec.ts → the existing
  hours-window case flaked once under five-worker contention after the new
  regression case passed; rerunning the regression alone passed.
- 2026-08-02: mise run lint printed 'Finished in 198s' with every check green,
  then hung for another ~8 minutes in an 'npm exec github...' -> 'npm install'
  child (sandbox egress is slow); had to pstree and kill -9 the mise process to
  get the shell back.
- 2026-08-02: Polled api.github.com from a bash loop to wait for CI; the egress
  proxy 403s it, so the loop parsed an error body as "no checks pending" and
  reported all-green while the test job was still running. Use the GitHub MCP
  tools for CI state in a sandbox — curl to api.github.com fails silently enough
  to look like success.
- 2026-08-04: Running any mise task with cwd inside .venv/src/vekna fails with
  'Config files in .../vekna/mise.toml are not trusted' instead of running the
  repo task. A git-sourced Poetry dependency ships its own mise.toml into the
  venv and mise's config discovery walks up into it. Needs a 'mise trust' note
  in docs/agents/sandbox.md.
- 2026-08-03: mise run lint-client fails locally with 'Cannot find module
  eslint-plugin-sonarjs' — the dep resolves to an 'invalid' link under
  node_modules/.aube. CI is fine; only the local run is blocked, so frontend
  lint can't be verified before pushing.
- 2026-08-05: mise run messages-check fails locally on 11 pre-existing '#,
  python-brace-format' flags: the local xgettext strips them, but main and CI
  both keep them. Regenerating the catalog silently drops the flags, so after
  'mise run messages' you have to revert the catalog and hand-apply only the
  real msgid deltas.
- 2026-08-05: mise run shots fails in the Claude Code sandbox: Chrome aborts
  with 'No usable sandbox' (unprivileged userns disabled). Playwright's own runs
  work, so had to hand-roll a playwright-core screenshot script pointed at the
  ms-playwright chromium binary. A --no-sandbox fallback in the shots task would
  save the detour.
- 2026-08-05: Scoping impeccable to two templates: 'mise run lint:impeccable
  path/to/file.html' silently drops the paths (the task body has no forwarding),
  so it scans every tracked HTML/CSS/JS file and looks hung for minutes. That is
  the same friction logged on 2026-07-14. Call '.venv/bin/python
  scripts/impeccable_lint.py PATH...' to scope it. Use the venv interpreter
  specifically: the script uses PEP 758 except syntax at line 102, valid only on
  3.14, so a bare 'python' (3.11 on PATH here) raises a SyntaxError that reads
  like a repo bug. Black under 3.14 normalizes to that form, so parenthesizing
  it fights the formatter and hk reverts the file mid-commit.
- 2026-08-07: git push over ssh fails in the review worktree: 'Bad owner or
  permissions on /etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf'. Committing
  works, pushing needs the user to run it (or the file's mode fixed to 0644
  root:root).
- 2026-08-07: docs/agents/sandbox.md documents the python3.14 install as
  apt+deadsnakes, but the CC-web egress proxy 403s ppa.launchpadcontent.net, so
  mise install leaves no 3.14 and the Python suite can't run. 3.13 is not a
  fallback — the code relies on 3.14 PEP 649 deferred annotations
  (pacts/legacy.py:229 uses SessionStatus 35 lines before its definition), so
  imports NameError. I wrongly concluded the sandbox couldn't run tests at all.
  `uv python install 3.14` fetches python-build-standalone from GitHub releases
  (reachable) in ~4s; worth making that the documented fallback in the
  SessionStart hook.
- 2026-08-02: `mise run test:py -- PATHS` appends the paths to the task's fixed
  'pytest -n auto tests/integration tests/unit', so a targeted run silently
  becomes the whole suite. Had to kill it and call .venv/bin/pytest directly.
  Calling pytest directly then needs `PYTHONPATH=src` and `. ./.env.test`
  sourced by hand — two more retries before a targeted run started.
- 2026-08-11: Burned a CI round because `djlint <path> --check` and the
  `lint:djlint` task disagree. The task is
  `djlint src --quiet --lint --check --format-css --format-js --profile=django`,
  and `--format-css` is what reformats CSS inside `<style>` blocks — without it
  my template checked clean locally and failed on CI, naming a file I had just
  checked. Nothing in the local output hints that a flag is missing. Copying the
  task's exact argv is the only reliable check when mise itself is unavailable;
  worth a line in docs/agents/sandbox.md next to the oxfmt note below.
- 2026-08-11: Hand-wrote a Playwright test and CI's `checks` job failed on oxfmt
  formatting. oxfmt only runs through `aube exec` inside lint:hk, which the
  sandbox's egress proxy blocks, so there is no way to format TS locally before
  pushing. Worked around it with `npm i oxfmt@0.56.0` in a scratch dir, run from
  the repo root so it picks up .oxfmtrc.json — that plain npm install is
  reachable is worth documenting in docs/agents/sandbox.md.
