---
title: 'tingle check passes locally in a clone with no local main branch'
severity: 'minor'
issue: 'zagrajmy/ludamus#1460'
---

## Expected Behavior

`mise run lint` (which runs `tingle check`) fails locally on the same added debt that CI's tingle job reports.

## Current Behavior

A Claude Code web sandbox starts from a detached HEAD with no local `main` branch. `mise run lint` passed, and then CI's tingle job failed on four new `wrong-assert` occurrences. After `git branch -f main origin/main`, the local `tingle check` reported them as well.

## Possible Solution

Have tingle compare against `origin/main` when `main` is missing, or have the SessionStart hook create `main` from `origin/main`.

## Minimal Reproducible Example

In a fresh sandbox clone, add an `assert response.` line to an integration test and run `mise run lint:tingle`.

## Context

It cost a CI round trip on zagrajmy/ludamus#1458.
