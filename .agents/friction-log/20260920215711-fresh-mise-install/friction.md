---
title: 'Fresh mise install times out after partially installing tools'
severity: 'minor'
issue: 'zagrajmy/ludamus#1346'
---

## Expected Behavior

A format task installs missing pinned tools once and proceeds without unrelated edits.

## Current Behavior

`mise run format:djlint` spent more than two minutes installing tools, timed out, and left Poetry half-installed so the first retry failed on its own existing executable. After installation completed, djlint rewrote 23 unrelated templates before returning failure.

## Possible Solution

Make tool installation atomic and scope the formatter to changed files or avoid rewriting files when the lint phase will fail.

## Minimal Reproducible Example

On a worktree missing the latest pinned tools, run `mise run format:djlint`.

## Context

This interrupted a one-template mobile cover fix and required restoring unrelated files.
