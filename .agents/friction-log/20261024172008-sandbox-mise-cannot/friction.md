---
title: 'Sandbox mise cannot install hk once mise.toml pins it with workflow=release.yml'
severity: 'major'
---

## Expected Behavior

`mise run <task>` works in a Claude Code web sandbox after merging main.

## Current Behavior

Every mise task fails before running:
``hk@2.7.0 failed: hk: option `workflow` is not used by the cargo backend``.
The hk pre-commit hook fails the same way, so commits fail too.

## Possible Solution

mise.toml now pins
`hk = { version = "2.7.0", workflow = "release.yml" }` (#1584), while
mise.sandbox.toml aliases hk to `cargo:hk`, which rejects `workflow`. Give
the sandbox its own hk pin without the option, or drop the option when
aliased.

## Minimal Reproducible Example

In a sandbox (MISE_ENV=sandbox) on main: `mise run test:unit`.

## Context

Worked around with
`MISE_DISABLE_TOOLS=python,pipx,github:reteps/dockerfmt,hk` for tasks, and
`HK=0 git commit` after running the checks by hand.
