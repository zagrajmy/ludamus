---
title: 'Frog reports a GitHub rate limit as a missing issues permission'
severity: 'minor'
---

## Expected Behavior

Frog's deferral reason names the condition that actually stopped the run.

## Current Behavior

Filing a 117-entry backlog hits GitHub's 80-per-minute content-creation limit.
Frog files 80 issues, then defers the remaining 37 with:

```
code:    NOT_AUTHORIZED
message: The token was rejected for zagrajmy/ludamus.
         It needs write access to issues.
```

The same token had just created 80 issues, so the permission was never
missing. GitHub answers a secondary rate limit with 403, and Frog maps every
403 to "needs write access". Re-dispatching a minute later filed the rest and
opened the sync pull request.

## Possible Solution

Distinguish a secondary rate limit from an authorization failure: GitHub sends
`retry-after` or a body containing "secondary rate limit" on the former. Defer
with a RATE_LIMITED code that tells the reader to wait rather than to widen
the workflow's permissions.

## Minimal Reproducible Example

Run `frog publish` with more than 80 unfiled entries and a token that holds
`issues: write`.

## Context

Hit on the first Action-only run after migrating off the Frog App, where the
whole backlog files at once.
