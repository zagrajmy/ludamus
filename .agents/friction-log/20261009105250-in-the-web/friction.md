---
title: 'In the web sandbox, mise run bootstrap in a fresh clone builds a Python 3.13 .venv'
severity: 'minor'
---

## Expected Behavior

`mise run bootstrap` in a fresh clone yields a Python 3.14 `.venv`, so
`mise run lint` passes there as it does in the session checkout.

## Current Behavior

Ran `mise run bootstrap` then `mise run lint` in a fresh clone (the shape of a
no-mistakes run worktree) under `MISE_ENV=sandbox` → `poetry install` built
`.venv` on the image's Python 3.13, because mise.sandbox.toml disables the mise
python and only the session hook builds a 3.14 venv; black aborted on 3.14
syntax and mypy could not import `mypy_django_plugin`.

## Possible Solution

Have bootstrap (or a sandbox-only prepare step) build `.venv` with
`uv venv --python 3.14` when the existing one is not 3.14, as
`.claude/hooks/session-start.sh` does.

## Minimal Reproducible Example

```bash
git clone . /tmp/wt && cd /tmp/wt
MISE_ENV=sandbox mise run bootstrap && MISE_ENV=sandbox mise run lint
```

## Context

Sandbox only; laptops get 3.14 from mise. Rebuilding `.venv` with uv on 3.14
made the same lint run pass.
