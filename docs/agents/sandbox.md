# Egress-restricted sandboxes

Claude Code on the web 403s every GitHub download (`api.github.com` included,
even for the session's own repos), while npm, PyPI, crates.io, the Go module
proxy, apt and jsDelivr stay reachable. Everything below is automated — this
page exists only so you know where the machinery lives.

The SessionStart hook (`.claude/hooks/session-start.sh`, remote sessions only)
sets `MISE_ENV=sandbox`, which makes mise load `mise.sandbox.toml` on top of
`mise.toml`. Its `[tool_alias]` table remaps each GitHub-release tool to a
reachable backend: hk via cargo, shellcheck/hadolint via PyPI binary wheels,
actionlint/dockerfmt via the Go module proxy (the sandbox image ships the rust
and go toolchains these backends compile with). Versions come from `mise.toml`
except for dockerfmt, shellcheck and hadolint, which `mise.sandbox.toml`
re-pins for the reasons below. The hook apt-installs python3.14 and pipx first
(the image preconfigures the deadsnakes PPA — on images without it the apt step
fails and the hook warns). aube and ast-grep need no substitute; mise.toml
installs them from npm everywhere (the unscoped `aube` npm package is
squatted — only `@endevco/aube` is ours; prod's `docker/mise.toml`
intentionally keeps the GitHub pin).

The sandbox image pre-bakes GitHub-layout installs of some of these tools.
When such an install clashes with the alias backend, mise skips installing it
but cannot list its bin paths — no shim, absent from `mise run` task PATH, hk
dies with "actionlint: not found". The hook self-heals: any aliased tool
without a shim after `mise install` gets its install purged and reinstalled
through the alias. Pre-baked layouts that happen to satisfy the alias (hk)
are kept as is.

PyPI wrapper packages add one more failure mode: they append a packaging
revision to the upstream version (shellcheck-py 0.11.0.1 wraps shellcheck
0.11.0), and mise passes a full `X.Y.Z` pin to uv verbatim as `==X.Y.Z`,
which matches nothing — `mise install` then fails outright and takes every
`mise run` down with it. `mise.sandbox.toml` carries a minor-version pin for
those two tools (`shellcheck = "0.11"`), which mise prefix-resolves to the
newest wrapper rev of that upstream release. With dockerfmt's, that makes
three pins duplicated outside `mise.toml` and nothing that checks them against
each other — dockerfmt's had already drifted two patches behind. Bump both
copies together whenever `mise.toml` moves.

Loosening `mise.toml` to `shellcheck = "0.11"` would delete all three lines,
since mise passes a full `X.Y.Z` through verbatim but prefix-resolves `X.Y`.
That is only safe if `X.Y` also prefix-resolves through the default aqua
backend laptops and CI use, which needs `api.github.com` and so cannot be
checked from a sandbox. Verify it on a laptop before making the change.

Playwright browsers: the image's `/opt/pw-browsers` build can lag the
`@playwright/test` pin, and Playwright launches only the pinned build, so the
hook's `mise run test:e2e:install` is load-bearing rather than a no-op. When
its `--with-deps` apt step breaks (image PPA metadata drift), the hook re-runs
`aube install` (the task's first step, and another way for it to fail) and
then installs one browser at a time. A single bare `playwright install`
downloads the browsers in one sequential loop and rethrows the first download
failure, so every browser queued behind the failure is skipped; per-browser
runs isolate it and report only what is genuinely unavailable. Missing OS libs
don't enter into it — the image ships no WebKit libs, but the host-requirement
check is caught and printed as a warning and the install still exits 0.

After that, `mise install` is green, `mise run` tasks work unchanged, and hk
runs as the pre-commit hook. Laptops never load `mise.sandbox.toml` — nothing
here activates without `MISE_ENV=sandbox`. If a session ever looks
half-provisioned, re-run `mise install` (MISE_ENV is exported session-wide).
When adding a new GitHub-release tool to `mise.toml`, add a matching alias or
substitute here, or sandbox sessions will wedge on its install.
