---
title: 'Reused E2E signup fixtures expire after an hour'
severity: 'minor'
---

## Expected Behavior

Reusing a running E2E server should make expired fixture state obvious before signup specs wait on a missing form.

## Current Behavior

I reran signup-age specs against a long-running prepared server. The seeded pending signups had exceeded the one-hour security timeout, so the tests reached the homepage and waited for age controls that were no longer present.

## Possible Solution

Refresh pending-signup fixtures before those specs, or report their expiry explicitly. Do not weaken the production timeout; reseeding the test data restored the run.

## Minimal Reproducible Example

Prepare and serve E2E data, leave the server running for more than an hour, then run signup-age.auth.spec.ts with server reuse enabled.

## Context

Found while verifying the privacy follow-ups to #1554.
