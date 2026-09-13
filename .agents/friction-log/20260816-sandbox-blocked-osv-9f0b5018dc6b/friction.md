---
title: 'Sandbox-blocked OSV advisory checks abort aube installation after dependency removal'
severity: 'minor'
context:
  recorded_on: '2026-08-16'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 249
issue: 'zagrajmy/ludamus#1214'
---

## Expected Behavior

## Current Behavior

aube install fails in the agent sandbox: aube-workspace.yaml paranoid:true
makes advisoryCheck required, and api.osv.dev is not on the sandbox network
allowlist, so every install dies with ERR_AUBE_ADVISORY_CHECK_FAILED after
wiping node_modules. Had to hand the install back to the user.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-16. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L249).

Historical observation; not reproduced as part of this migration.
