---
title: 'E2E bootstrap times out while downloading vendor files'
severity: 'minor'
---

## Expected Behavior
Focused Playwright tests start reliably.

## Current Behavior
The second run stalled in django-admin downloadvendor until Playwright’s 180-second webServer startup timeout aborted preparation.

## Possible Solution
Bound vendor download retries or let focused runs reuse prepared fixtures.

## Minimal Reproducible Example
mise run test:e2e -- uncategorized-proposal.spec.ts --project=chromium

## Context
The previous bootstrap completed; standalone preparation on retry succeeded in 198 seconds.
