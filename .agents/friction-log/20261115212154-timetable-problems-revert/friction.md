---
title: 'timetable-problems revert test once timed out waiting for a second confirm dialog'
severity: 'minor'
---

### Expected Behavior

'reverting the removal from the activity log puts the session back' in tests/e2e/tests/timetable-problems.spec.ts passes every run.

### Current Behavior

Once in six runs of the four timetable specs together, it timed out at line 60 waiting for getByRole('alertdialog') Revert, though the activity log already showed the Reverted row.

### Possible Solution

Unknown. Check whether the confirm dialog closes before the second lookup, or whether the step runs twice.

### Minimal Reproducible Example

mise run test:e2e -- tests/timetable.spec.ts tests/timetable-conflict-count.spec.ts tests/timetable-problems.spec.ts tests/timetable-publish.spec.ts --trace off

### Context

Seen while working on schedule drag-and-drop, which does not touch the activity log.
