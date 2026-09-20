---
title: 'Direct djlint checks omit the task''s embedded CSS and JS formatting flags'
severity: 'minor'
context:
  recorded_on: '2026-08-11'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 182
issue: 'zagrajmy/ludamus#1201'
---

## Expected Behavior

## Current Behavior

Burned a CI round because `djlint <path> --check` and the `lint:djlint` task
disagree. The task is `djlint src --quiet --lint --check --format-css
--format-js --profile=django`, and `--format-css` is what reformats CSS inside
`<style>` blocks — without it my template checked clean locally and failed on
CI, naming a file I had just checked. Nothing in the local output hints that a
flag is missing. Copying the task's exact argv is the only reliable check when
mise itself is unavailable; worth a line in docs/agents/sandbox.md next to the
oxfmt note below.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-11. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L182).

Historical observation; not reproduced as part of this migration.
