---
title: 'Sandbox lacks working SSH pushes and a PostgreSQL test service'
severity: 'minor'
context:
  recorded_on: '2026-08-08'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 176
issue: 'zagrajmy/ludamus#1200'
---

## Expected Behavior

## Current Behavior

git push over SSH fails in this worktree: 'Bad owner or permissions on
/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf' (symlink owned by
nobody:nogroup). Worked around with: git -c credential.helper='!gh auth
git-credential' push https://github.com/zagrajmy/ludamus.git HEAD:the-branch.
Also, no local Postgres and no docker, so 'mise run test:postgres' errors on
connection refused for all 7 marked tests.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-08. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L176).

Historical observation; not reproduced as part of this migration.
