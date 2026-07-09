# Egress-restricted sandboxes

Claude Code on the web 403s every GitHub download (`api.github.com` included,
even for the session's own repos), while npm, PyPI, crates.io, the Go module
proxy, apt and jsDelivr stay reachable. Everything below is automated — this
page exists only so you know where the machinery lives.

The SessionStart hook (`.claude/hooks/session-start.sh`, remote sessions only)
disables the mise tools whose GitHub install failed, then runs
`scripts/sandbox-bootstrap`, which substitutes each one from a reachable host:
python via apt (deadsnakes), hk via cargo, shellcheck/hadolint via PyPI
binary wheels, actionlint/dockerfmt via the Go module proxy — declared in the gitignored
`.mise.local.toml` so shims expose the usual binary names. aube and ast-grep
need no substitute; mise.toml installs them from npm everywhere (the unscoped
`aube` npm package is squatted — only `@endevco/aube` is ours; prod's
`docker/mise.toml` intentionally keeps the GitHub pin).

After that, `mise install` is green, `mise run` tasks work unchanged, and hk
runs as the pre-commit hook. If a session ever looks half-provisioned, run
`bash scripts/sandbox-bootstrap` again — it is idempotent.
