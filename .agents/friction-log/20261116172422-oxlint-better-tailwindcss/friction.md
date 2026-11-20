---
title: 'oxlint better-tailwindcss plugin fails with Atomics.wait() timed-out under machine load'
severity: 'minor'
---

### Expected Behavior

`hk` oxlint step reports only lint findings.

### Current Behavior

With load average ~13 on 8 cores, `mise run pr-fix` ran oxlint for 444s and reported 13 errors, all `Error running JS plugin: Internal error: Atomics.wait() failed: timed-out` from synckit in eslint-plugin-better-tailwindcss (enforce-canonical-classes), on src/ludamus/client/src/parley/*.tsx. The same files lint clean in 22s when run alone.

### Possible Solution

Raise the synckit worker timeout for the oxlint step, or run oxlint with fewer threads when the machine is busy.

### Minimal Reproducible Example

Run `mise run pr-fix` while other heavy jobs (parallel worktree test runs) load the machine.

### Context

The gate turns red on a worker timeout, not on a lint finding.
