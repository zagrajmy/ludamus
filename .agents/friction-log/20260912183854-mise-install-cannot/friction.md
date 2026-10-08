---
title: 'npm and npx cannot run where ~/.npm is read-only'
severity: 'minor'
---

## Expected Behavior

`mise run pr-fix` runs its npm-backed steps in the sandbox: `mise install`
adds `npm:frog@1.1.0`, and `lint:impeccable` shells out to
`npx --yes github:pbakaus/impeccable#... detect`.

## Current Behavior

npm fails before any download completes:

```
npm error code ENOENT
npm error syscall mkdir
npm error path /home/radek/.npm/_cacache
npm error enoent Invalid response body while trying to fetch https://registry.npmjs.org/frog: ENOENT: no such file or directory, mkdir '/home/radek/.npm/_cacache'
mise ERROR Failed to install npm:frog@1.1.0
```

The sandbox mounts `$HOME` read-only and bind-mounts only a few writable
paths. Under `~/.npm` it whitelists `_logs` and `_npx` but not `_cacache`, so
npm's default cache directory can never be created. The message blames the
registry response, which sends you looking at the proxy instead of the mount
table.

`lint:impeccable` fails the same way, and a warm `~/.npm/_npx` does not save
it — npx still touches `_cacache` on every invocation, so the failure recurs
on each run rather than only on a cold one.

## Possible Solution

Whitelist `~/.npm` (or `~/.npm/_cacache`) as writable in the sandbox mount
set, or export `npm_config_cache` to a path under `~/.cache`, which is already
writable.

## Minimal Reproducible Example

```
mise install npm:frog@1.1.0          # ENOENT on mkdir _cacache
mise run lint:impeccable             # same, via npx
npm_config_cache=~/.cache/npm mise install npm:frog@1.1.0   # succeeds
```

## Context

Hit while making `mise run pr-fix` green on `feat/export-everywhere`.
