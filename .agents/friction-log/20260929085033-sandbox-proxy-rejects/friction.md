---
title: 'Sandbox proxy rejects GitHub''s numeric-ID pagination links'
severity: 'minor'
---

## Expected Behavior

`gh api --paginate`-style callers (the optimise-github-actions skill's `measure.mjs`) can follow GitHub's `Link: rel="next"` URLs through the sandbox proxy.

## Current Behavior

With no `gh` in the sandbox, I ran `measure.mjs` through a curl-backed `gh api` shim. Page 2 of every list returned 403: GitHub's next links use `/repositories/{id}/...`, which the agent proxy refuses ("Numeric-ID repository paths are not supported through this proxy"). Python 3.14's urllib also rejects the proxy CA ("CA cert does not include key usage extension"), so the shim had to shell out to curl.

## Possible Solution

Rewrite `/repositories/{id}/` to `/repos/{owner}/{repo}/` before following a next link, or make `gh` available in the sandbox.

## Minimal Reproducible Example

`curl -H "Authorization: Bearer $GITHUB_TOKEN" 'https://api.github.com/repositories/998007543/actions/runs?per_page=100&page=2'` returns 403.

## Context

Cost two failed runs of a ~5 minute measurement before the CI audit could start.
