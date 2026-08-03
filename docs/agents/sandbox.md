# Egress-restricted sandboxes

Claude Code on the web 403s every GitHub download (`api.github.com` included,
even for the session's own repos), while npm, PyPI, crates.io, the Go module
proxy, apt and jsDelivr stay reachable. Everything below is automated — this
page exists only so you know where the machinery lives.

The SessionStart hook (`.claude/hooks/session-start.sh`, remote sessions only)
sets `MISE_ENV=sandbox`, which makes mise load `mise.sandbox.toml` on top of
`mise.toml`. Its `[tool_alias]` table remaps each GitHub-release tool to a
reachable backend at the version already pinned in `mise.toml`: hk via cargo,
shellcheck/hadolint via PyPI binary wheels, actionlint/dockerfmt via the Go
module proxy (the sandbox image ships the rust and go toolchains these
backends compile with). The hook apt-installs python3.14 and pipx first (the
image preconfigures the deadsnakes PPA — on images without it the apt step
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

PyPI wrapper packages add one more failure mode, handled in `mise.toml`
rather than here: they append a packaging revision to the upstream version
(shellcheck-py 0.11.0.1 wraps shellcheck 0.11.0), and mise passes an exact
`X.Y.Z` pin to uv verbatim as `==X.Y.Z`, which matches nothing on PyPI. So
shellcheck and hadolint are pinned as `prefix:0.11.0` / `prefix:2.14.0`:
mise resolves a prefix against the registry, picking the wrapper in sandboxes
and the identical exact version on the GitHub-release backends laptops use.
Keep the `prefix:` when bumping either pin; a bare `X.Y.Z` wedges every
sandbox `mise install`.

Playwright browsers: the image's `/opt/pw-browsers` build can lag the
`@playwright/test` pin, and Playwright launches only the pinned build, so the
hook's `mise run test:e2e:install` is load-bearing rather than a no-op. When
that task fails for any reason — its `--with-deps` apt step hitting image PPA
metadata drift is the usual one, but `aube install` runs first and a browser
download can fail on its own — the hook re-runs `aube install` and then
installs one browser at a time via `test:e2e:install:browser`. A single bare
`playwright install` downloads the browsers in one sequential loop and rethrows
the first download failure, so every browser queued behind the failure is
skipped; per-browser runs isolate it and report only what is genuinely
unavailable. Missing OS libs don't enter into it — the image ships no WebKit
libs, but the host-requirement check is caught and printed as a warning and the
install still exits 0. The Playwright CDN itself is reachable through the proxy.

After that, `mise install` is green, `mise run` tasks work unchanged, and hk
runs as the pre-commit hook. Laptops never load `mise.sandbox.toml` — nothing
here activates without `MISE_ENV=sandbox`. If a session ever looks
half-provisioned, re-run `mise install` (MISE_ENV is exported session-wide).
When adding a new GitHub-release tool to `mise.toml`, add a matching alias or
substitute here, or sandbox sessions will wedge on its install.
