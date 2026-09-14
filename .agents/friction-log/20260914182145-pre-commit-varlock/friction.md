---
title: 'Pre-commit varlock step fails in worktrees with symlinked node_modules'
severity: 'minor'
---

## Expected Behavior

Committing in a sandbox worktree whose `node_modules` is a symlink to the main checkout runs the hk pre-commit steps and succeeds.

## Current Behavior

The `varlock` step (`aube exec varlock scan --staged`) tries to auto-install `tests/e2e/node_modules/@axe-core/playwright`, then aborts with "refusing to use a modules directory that is not inside the project" because `node_modules` resolves outside the worktree. Every other step passes. Commits only go through with `HK_SKIP_STEPS=varlock`.

## Possible Solution

Let the varlock step tolerate a symlinked `node_modules`, or skip the e2e workspace auto-install for `--staged` scans.

## Minimal Reproducible Example

In a fresh worktree: `ln -s /home/user/ludamus/node_modules node_modules`, stage any file, commit.

## Context

Blocked every commit of a template/TS refactor until the step was skipped by env var.
