---
title: 'Aube refuses shared node_modules in isolated follow-up worktrees'
severity: 'minor'
---

## Expected Behavior
Run TypeScript/client lint using preconfigured shared dependencies without installing.

## Current Behavior
Aube tries to auto-install and refuses symlinked node_modules outside the worktree. Direct Oxlint also cannot resolve eslint-plugin-sonarjs.

## Possible Solution
Provide a read-only invocation for existing shared dependencies.

## Minimal Reproducible Example
Run mise run ts-check or mise run lint-client from /tmp/ludamus-followups/modal-lifecycle.

## Context
Isolated follow-up branch; shared environment must not be modified. Direct installed TypeScript binary succeeds.

2026-11-08: recurred in a `.claude/worktrees/` agent worktree. With
`tests/e2e/node_modules` and `src/ludamus/client/node_modules` symlinked from
the main checkout, `mise run test:e2e:prep` stopped at its `aube install` step
("refusing to use a modules directory that is not inside the project").
Removing the symlinks and letting `aube install` populate the worktree from
the lockfile worked.
