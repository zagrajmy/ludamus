---
title: 'mise run aborts on the hk cargo alias in the web sandbox, so test:e2e:prep never runs'
severity: 'minor'
---

## Expected Behavior

`mise run test:e2e:prep` migrates, seeds and builds the client in a Claude Code web sandbox, as docs/agents/sandbox.md describes.

## Current Behavior

With MISE_ENV=sandbox every `mise run` (any task, frog included) exits after `Failed to install cargo:hk@2.7.0: hk: option `workflow` is not used by the cargo backend` (mise 2026.10.21). No task body runs.

## Possible Solution

Keep `workflow = "release.yml"` out of the hk pin when the sandbox alias maps it to cargo (mise.sandbox.toml), or set the option only in the non-sandbox config.

## Minimal Reproducible Example

```sh
export MISE_ENV=sandbox
mise run test:e2e:prep
```

## Context

Ran the prep steps by hand (migrate, createcachetable, downloadvendor, compilemessages, bootstrap_*.py, client build) to seed dev.e2e.sqlite3 for the rat-stack experiment; logged this entry by calling the frog binary directly.
