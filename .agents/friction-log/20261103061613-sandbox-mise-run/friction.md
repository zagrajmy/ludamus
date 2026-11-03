---
title: 'Sandbox mise run aborts: hk `workflow` option rejected by cargo backend'
severity: 'major'
---

## Expected Behavior

`mise run <task>` starts in a Claude Code web sandbox (`MISE_ENV=sandbox`).

## Current Behavior

Every `mise run` aborts before the task starts: mise 2026.10.25 rejects
`hk = { version = "2.7.0", workflow = "release.yml" }` once `mise.sandbox.toml`
aliases hk to `cargo:hk` ("option `workflow` is not used by the cargo backend").

## Possible Solution

Give the sandbox alias its own version-only table entry, or drop `workflow`
from the shared pin. Workaround: `MISE_DISABLE_TOOLS=hk mise run …`.

## Minimal Reproducible Example

`MISE_ENV=sandbox mise run lint-client`

## Context

Blocked running lint and e2e tasks while verifying a client change.
