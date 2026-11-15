---
title: 'Parallel worktree e2e runs collide on the fixed :8000/:8001 ports'
severity: 'minor'
---

### Expected Behavior

Two worktrees can each run `mise run test:e2e -- tests/parley` at the same time.

### Current Behavior

The second run's webServer fails with "That port is already in use" (or, without CI=1, silently reuses the other checkout's server on :8000).

### Possible Solution

Derive the e2e port, ROOT_DOMAIN and stored auth-state cookie domains from one variable, so a run can pick a free port.

### Minimal Reproducible Example

Start `mise run test:e2e` in one worktree, then in another; the second cannot start its server.

### Context

ROOT_DOMAIN in .env.e2e and the stored auth states pin localhost:8000, and the privacy server pins :8001.
