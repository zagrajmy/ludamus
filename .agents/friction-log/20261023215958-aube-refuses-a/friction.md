---
title: 'aube refuses a node_modules symlinked into a worktree, so messages and e2e fail'
severity: 'minor'
---

## Expected Behavior

Symlinking node_modules from the main checkout into a fresh worktree lets mise tasks run without a reinstall.

## Current Behavior

mise run messages ran aubr, which auto-installed and failed with 'refusing to use a modules directory that is not inside the project'. Removing the symlinks and running aube install (under a second, from the store) fixed it.

## Possible Solution

Worktree setup runs aube install instead of symlinking node_modules.

## Minimal Reproducible Example

ln -s ../main/node_modules node_modules && mise run messages

## Context

Worktree for the DSA contact page branch.
