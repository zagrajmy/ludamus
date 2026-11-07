---
title: 'CLA setup instructions suggest a recheck comment that the workflow ignores'
severity: 'minor'
issue: 'zagrajmy/ludamus#1521'
---

## Expected Behavior

After creating cla-signatures and configuring CLA_SIGNATURES_TOKEN, commenting recheck on #1510 should run the CLA check.

## Current Behavior

The cla.yml job only accepts pull_request_target events or comments containing the signing phrase, so plain recheck produces a skipped run. A direct retry initialized signatures/v1/cla.json but failed because contributor-assistant v2.6.1 unconditionally throws after creating that file; a subsequent run passed.

## Possible Solution

Accept the action's recheck command in the issue_comment job condition and document the one-time initialization retry.

## Minimal Reproducible Example

See #1511 setup instructions, #1510 comment 6158980726, skipped run 38497055145, and attempts 2 and 3 of run 38411638682.

## Context

The branch and secret were configured successfully, but the documented command did not execute the bot. No CLA was signed on a user's behalf.
