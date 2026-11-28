---
title: 'messages-resolve leaves stale-vs-new translation variants for hand-fixing'
severity: 'minor'
---

## Expected Behavior

`mise run messages-resolve` settles a `django.po` merge conflict when only one side changed each translation.

## Current Behavior

Merging main's Polish copy revision (#1869) into a branch whose `django.po` only reorders entries made `messages-resolve` flag 54 msgcat ours/theirs variants for hand-fixing. In every one, the branch side was just the merge-base text.

## Possible Solution

Do a three-way pick: for each flagged entry, keep the side whose msgstr differs from the merge base, and only flag entries both sides changed.

## Minimal Reproducible Example

On a branch with a reordered `django.po`, `git merge --no-commit origin/main` where main rewrote 54 translations, then `mise run messages-resolve`.

## Context

Resolving by hand would have meant 54 manual edits during an automated main merge into PR #1400; a throwaway script applying the merge-base rule resolved all of them.
