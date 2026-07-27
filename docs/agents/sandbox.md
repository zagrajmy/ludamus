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

PyPI wrapper packages add one more failure mode: they append a packaging
revision to the upstream version (shellcheck-py 0.11.0.1 wraps shellcheck
0.11.0), and mise passes a full `X.Y.Z` pin to uv verbatim as `==X.Y.Z`,
which matches nothing. The hook's last resort covers it: any aliased tool
still shimless after the reinstall is retried with its mise.toml pin trimmed
one segment (`shellcheck@0.11`), which mise prefix-resolves to the wrapper's
version and links back to the pinned one. Bumping a pin in `mise.toml` needs
no sandbox-side edit.

Playwright browsers: the image's `/opt/pw-browsers` build can lag the
`@playwright/test` pin, so the hook runs `mise run test:e2e:install`; when its
`--with-deps` apt step breaks (image PPA metadata drift), it falls back to a
plain `playwright install` — the Playwright CDN is reachable through the
proxy and the image already ships Chromium's OS libs.

After that, `mise install` is green, `mise run` tasks work unchanged, and hk
runs as the pre-commit hook. Laptops never load `mise.sandbox.toml` — nothing
here activates without `MISE_ENV=sandbox`. If a session ever looks
half-provisioned, re-run `mise install` (MISE_ENV is exported session-wide).
When adding a new GitHub-release tool to `mise.toml`, add a matching alias or
substitute here, or sandbox sessions will wedge on its install.
