---
title: 'Proxy-denied GitHub CI polling can report false success'
severity: 'minor'
context:
  recorded_on: '2026-08-02'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 138
---

## Expected Behavior

## Current Behavior

Polled api.github.com from a bash loop to wait for CI; the egress proxy 403s
it, so the loop parsed an error body as "no checks pending" and reported
all-green while the test job was still running. Use the GitHub MCP tools for CI
state in a sandbox — curl to api.github.com fails silently enough to look like
success.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-02. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L138).

Historical observation; not reproduced as part of this migration.
