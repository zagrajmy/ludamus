---
title: 'lint:impeccable hangs silently in the Claude web sandbox'
severity: 'minor'
---

## Expected Behavior

`mise run lint:impeccable` fails fast with a network error when it cannot fetch the impeccable spec.

## Current Behavior

In a Claude Code web sandbox it fetches `github:pbakaus/impeccable#...`, which the egress proxy 403s, and the command sits silent for minutes until it is killed.

## Possible Solution

Put a timeout on the npx call, or vendor the spec so no GitHub fetch is needed.

## Minimal Reproducible Example

`timeout 110 python scripts/impeccable_lint.py src/ludamus/templates/whiteboard/board.html` prints nothing and is terminated.

## Context

Checking new templates for the board slice; the check had to be skipped.
