---
title: 'Sandbox SSH pushes fail on system ssh-proxy configuration ownership'
severity: 'minor'
context:
  recorded_on: '2026-08-01'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 127
issue: 'zagrajmy/ludamus#1191'
---

## Expected Behavior

## Current Behavior

git push over SSH fails with 'Bad owner or permissions on
/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf' (symlink owned by
nobody:nogroup); worked around with git -c credential.helper='!gh auth git-
credential' push <https://github.com/zagrajmy/ludamus.git> HEAD:the-branch

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-01. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L127).

Historical observation; not reproduced as part of this migration.
