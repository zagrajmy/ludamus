# Egress-restricted sandboxes

Claude Code on the web 403s every GitHub download (`api.github.com` included,
even for the session's own repos), while npm, PyPI, crates.io, the Go module
proxy, apt and jsDelivr stay reachable. Everything below is automated — this
page exists only so you know where the machinery lives.

The SessionStart hook (`.claude/hooks/session-start.sh`, remote sessions only)
sets `MISE_ENV=sandbox`, which makes mise load `mise.sandbox.toml` on top of
`mise.toml`. That file disables each GitHub-release tool and re-provides it at
the same version from a reachable registry: hk via cargo, shellcheck/hadolint
via PyPI binary wheels, actionlint/dockerfmt via the Go module proxy. The hook
apt-installs python3.14 and pipx first (the sandbox image preconfigures the
deadsnakes PPA — on images without it the apt step fails and the hook warns).
aube and ast-grep need no substitute; mise.toml installs them from npm
everywhere (the unscoped `aube` npm package is squatted — only `@endevco/aube`
is ours; prod's `docker/mise.toml` intentionally keeps the GitHub pin).

After that, `mise install` is green, `mise run` tasks work unchanged, and hk
runs as the pre-commit hook. Laptops never load `mise.sandbox.toml` — nothing
here activates without `MISE_ENV=sandbox`. If a session ever looks
half-provisioned, re-run `mise install` (MISE_ENV is exported session-wide) or
bump version pins in `mise.sandbox.toml` alongside `mise.toml`.
