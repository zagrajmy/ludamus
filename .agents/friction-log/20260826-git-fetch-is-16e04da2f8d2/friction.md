---
title: 'git fetch is blocked by invalid sandbox SSH proxy configuration ownership'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 350
issue: 'zagrajmy/ludamus#1229'
---

## Expected Behavior

## Current Behavior

git fetch origin failed: 'Bad owner or permissions on
/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf' — could not verify branch base
against remote; local origin/main was current so proceeded

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L350).

Historical observation; not reproduced as part of this migration.
