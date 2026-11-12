---
title: 'Impeccable wrapper gives no diagnosis when npm exits with empty streams'
severity: 'minor'
context:
  recorded_on: '2026-08-18'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 282
issue: 'zagrajmy/ludamus#1218'
---

## Expected Behavior

## Current Behavior

lint:impeccable failed for ~20 minutes on every branch, locally and on CI, with
a bare 'impeccable failed (exit 1)'. npx installed the SHA-pinned CLI (--help
worked, and the cached copy ran clean when invoked by path) but 'npm exec ...
detect' exited 1 with no stdout or stderr, so the wrapper had nothing to print.
It cleared on its own. run_detect should surface npm's own exit path rather
than only the child's streams, otherwise a registry hiccup is indistinguishable
from a real finding.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-18. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L282).

Historical observation; not reproduced as part of this migration.

On 2026-10-15, PR #1516's checks job failed with only
`impeccable failed (exit 152):` and no detector findings or child output. The
same lint task passed locally. GitHub would not rerun the completed job while
other jobs in its workflow were still running.

[CI job log](https://github.com/zagrajmy/ludamus/actions/runs/38785914701/job/116598333478).
