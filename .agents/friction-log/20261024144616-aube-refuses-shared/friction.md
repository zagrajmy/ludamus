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
