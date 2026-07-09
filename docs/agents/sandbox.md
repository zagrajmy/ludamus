# Egress-restricted sandboxes

Claude Code on the web (and similar CI-ish sandboxes) sits behind an egress
proxy that 403-blocks GitHub release downloads (github.com and
api.github.com are scoped to the repos attached to the session). pypi.org,
files.pythonhosted.org, registry.npmjs.org, nodejs.org and cdn.jsdelivr.net
stay reachable, and the base image already has the deadsnakes PPA configured.

aube installs normally: mise.toml pulls it from npm (`npm:@endevco/aube`,
with `npm_args = "--ignore-scripts=false"` because the package's preinstall
fetches the platform binary sub-package — also from the npm registry). The
production image is intentionally unchanged: `docker/mise.toml` keeps
`github:endevco/aube`. Never use the unscoped `aube` npm package — that name
is squatted by an unrelated project.

Still GitHub-blocked, with their fallbacks:

| Tool | Status in sandbox | Alternative |
| --- | --- | --- |
| `python` | blocked (python-build-standalone) | apt deadsnakes (this hook) |
| `ast-grep` | blocked (GitHub release) | `pip install ast-grep-cli` (PyPI) |
| `shellcheck`, `pipx` | blocked | `apt-get install shellcheck pipx` |
| `hk`, `actionlint`, `hadolint`, `github:reteps/dockerfmt` | blocked | skip — lint-only; CI covers them |

## What the SessionStart hook does

`.claude/hooks/session-start.sh` (remote sessions only, gated on
`CLAUDE_CODE_REMOTE`) disables the mise tools that failed to install, then
runs `scripts/sandbox-bootstrap`, which applies fallbacks only where the
normal path is missing:

1. `python3.14` absent → `apt-get install -y python3.14 python3.14-venv`
   (deadsnakes; skipped when not root or no apt)
2. `.venv` absent → create it with `python3.14 -m venv`, then
   `poetry install --no-root` into it (poetry itself comes from PyPI if
   missing)
3. `aube` unavailable (it normally installs from npm; this is the
   belt-and-braces path) → `npm install` in `src/ludamus/client` (the stray
   `package-lock.json` npm writes is deleted — `aube-lock.yaml` is the real
   lockfile) and `vite build` for the frontend assets

Every step is idempotent and best-effort: a failure prints a `WARN` line and
the rest still runs. Where `mise` works normally (local dev), each step
detects that and skips itself, so the script is safe to run anywhere.

## Manual equivalents

If the hook did not run, the same recovery by hand:

```bash
apt-get update && apt-get install -y python3.14 python3.14-venv
python3.14 -m venv .venv
poetry env use .venv/bin/python && poetry install --no-root
(cd src/ludamus/client && npm install && rm -f package-lock.json \
  && ./node_modules/.bin/vite build)
```

`mise run` tasks work once `.venv` is populated (mise activates it via
`_.python.venv`). Tasks that shell through `aubr varlock` (e.g. `mise run dj`)
do not — call `django-admin` directly with env from `.env.test` instead:

```bash
env $(grep -v '^#' .env.test | xargs) PYTHONPATH=src \
  DJANGO_SETTINGS_MODULE=ludamus.edges.settings \
  .venv/bin/django-admin downloadvendor  # jsdelivr is reachable

env $(grep -v '^#' .env.test | xargs) PYTHONPATH=src \
  DJANGO_SETTINGS_MODULE=ludamus.edges.settings \
  .venv/bin/pytest tests/unit
```
