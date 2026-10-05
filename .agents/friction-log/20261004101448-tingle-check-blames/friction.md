---
title: 'tingle check blames other PRs'' debt when the sandbox''s local main is stale'
severity: 'minor'
---

### Expected Behavior

`mise run lint:tingle` reports only the debt the branch adds relative to the commit it was cut from.

### Current Behavior

In a sandbox clone whose local `main` (and origin/main ref) lagged behind the branch's base, it reported +12 debt in files the branch never touched (mills/*, gates/web/django/event/propose.py) and failed the lint gate.

### Possible Solution

Have tingle (or the mise task) warn when `main` isn't the branch's merge base, or diff against `git merge-base HEAD origin/main` after a fetch.

### Minimal Reproducible Example

Clone with a stale `main`, branch from a newer origin commit, run `mise run lint:tingle`. Fixed by `git fetch origin main && git branch -f main origin/main`.

### Context

Hit while redesigning /dev/emails/ in a Claude Code web sandbox.
