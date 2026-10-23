---
title: 'aube refuses a node_modules symlinked from the main checkout into a worktree'
severity: 'minor'
---

## Expected Behavior

A worktree can reuse the main checkout's node_modules through a symlink, as
agent setup instructions suggest, and `mise run dj ...` runs.

## Current Behavior

With `node_modules` and `src/ludamus/client/node_modules` symlinked from
/home/user/ludamus, `mise run dj makemigrations` auto-installed and failed:
"failed to link workspace node_modules: refusing to use a modules directory
that is not inside the project".

## Possible Solution

Drop the symlink advice for node_modules: deleting the symlinks and letting
aube install from its store took under a second.

## Minimal Reproducible Example

ln -s /home/user/ludamus/node_modules node_modules; mise run dj check

## Context

One failed run and a detour while starting the DSA report feature (#1566).
