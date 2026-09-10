---
title: 'PR body updates fail through deprecated gh GraphQL and PTY stdin'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 38
---

## Expected Behavior

## Current Behavior

Updating the PR body with gh pr edit failed on the deprecated Projects Classic
GraphQL field; gh api with a PTY stdin payload also produced HTTP 400. A direct
REST PATCH with a form field worked.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L38).

Historical observation; not reproduced as part of this migration.
