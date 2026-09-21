---
title: 'Local agent-device XCUITest runner fails to build with xcodebuild exit 70'
severity: 'minor'
context:
  recorded_on: '2026-08-27'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 394
issue: 'zagrajmy/ludamus#1238'
---

## Expected Behavior

## Current Behavior

Local iOS harness validation reached agent-device, but its XCUITest runner
build failed with xcodebuild code 70 on the local simulator, so Safari
bootstrap behavior still needs the macOS CI runner for end-to-end verification.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-27. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L394).

Historical observation; not reproduced as part of this migration.
