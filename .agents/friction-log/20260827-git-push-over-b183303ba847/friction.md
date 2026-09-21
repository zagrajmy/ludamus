---
title: 'git push over SSH is blocked by sandbox proxy-config permissions'
severity: 'minor'
context:
  recorded_on: '2026-08-27'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 391
issue: 'zagrajmy/ludamus#1237'
---

## Expected Behavior

## Current Behavior

git push over ssh origin fails: 'Bad owner or permissions on
/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf' (symlink owned by
nobody:nogroup); pushed via the https-origin remote instead

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-27. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L391).

Historical observation; not reproduced as part of this migration.
