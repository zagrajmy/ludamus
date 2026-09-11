---
title: 'Each iOS spec pays a separate XCUITest runner launch'
severity: 'minor'
context:
  recorded_on: '2026-08-28'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 417
---

## Expected Behavior

## Current Behavior

agent-device keys the XCUITest runner to a session and stops it on session
close, so a per-spec session pays its own 125-148s runner launch; only
build-for-testing is shared across a job. Read it out of the uploaded
daemon.log (four distinct AgentDeviceRunner.env.session-*.xctestrun launches),
not the docs.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-28. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L417).

Historical observation; not reproduced as part of this migration.
