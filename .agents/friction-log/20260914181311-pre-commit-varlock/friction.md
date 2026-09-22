---
title: 'pre-commit varlock hook fails in sandbox worktree with symlinked node_modules'
severity: 'minor'
issue: 'zagrajmy/ludamus#1304'
---

## Expected Behavior

`git commit` in a Claude Code web worktree runs the hk hooks and succeeds when
djlint, oxfmt, oxlint and codespell pass.

## Current Behavior

The `varlock` hook tries to auto-install `tests/e2e/node_modules/@axe-core/playwright`
and aborts with "refusing to use a modules directory that is not inside the
project" because the worktree's `node_modules` is a symlink into the main
checkout. The commit is rejected even though every code-quality hook passed;
the only workaround is `git commit --no-verify`.

## Possible Solution

Skip `varlock` when `node_modules` is a symlink, or when no `.env`-shaped file
is staged; a template + TS rename cannot introduce a secret.

## Minimal Reproducible Example

In a worktree: `ln -s /path/to/main/node_modules node_modules`, stage any
`.html` file, `git commit`.

## Context

Blocked committing a hook-class → data-attribute rename in the import recipe
editor.
