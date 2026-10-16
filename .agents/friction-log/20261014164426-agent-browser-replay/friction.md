---
title: 'agent-browser replay of seeded Playwright auth state redirects to login'
severity: 'minor'
---

## Expected Behavior

The seeded Playwright storageState should authenticate agent-browser on localhost:8000.

## Current Behavior

Opening the profile with --state tests/e2e/.auth-state-profile.json redirected to login; state load did too. The same file passed the authenticated Playwright profile and dashboard checks. A subsequent mise run shots attempt timed out, so verified Playwright artifacts were used instead.

## Possible Solution

Check compatibility of agent-browser state replay with the seeded cookie format.

## Minimal Reproducible Example

Start mise run test:e2e:serve after an e2e seed. Run aubx agent-browser --session banner-cleanup --state tests/e2e/.auth-state-profile.json open http://localhost:8000/crowd/profile/.

## Context

UI verification of the static-banner cleanup; screenshots were captured by the passing E2E suite.
