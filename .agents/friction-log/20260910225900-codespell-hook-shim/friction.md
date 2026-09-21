---
title: 'Codespell hook shim points at a deleted worktree venv'
severity: 'minor'
issue: 'zagrajmy/ludamus#1277'
---

## Expected Behavior

`git commit` runs the hk pre-commit chain to completion in any checkout.

## Current Behavior

The `codespell` hook aborts, taking `detect-private-key`, `end-of-file-fixer`,
`trailing-whitespace`, `yamllint`, `actionlint` and `varlock` down with it:

```
/Users/…/mise/installs/python/3.14/bin/codespell: line 2:
  /private/tmp/…/scratchpad/mainwt/.venv/bin/python: No such file or directory
```

The mise-installed shim hardcodes a shebang into the venv of whichever
worktree first installed it. That worktree is gone, so every commit fails
until the hook is bypassed with `--no-verify`.

## Possible Solution

Reinstall the tool so the shim points at the mise python, or install
codespell as a repository dev dependency rather than a mise-global one.

## Minimal Reproducible Example

Commit from a worktree other than the one that installed codespell.

## Context

Hit while committing a one-file workflow change.
