---
title: 'Pre-commit oxlint autofix rewrites keyCode 229 into event.key ''å'''
severity: 'minor'
---

## Expected Behavior

The pre-commit `oxlint` fix step only applies fixes that keep behaviour, or leaves the rest as errors to fix by hand.

## Current Behavior

The hk `oxlint` step's autofix for `unicorn/prefer-keyboard-event-key` rewrote `event.keyCode === 229` (the IME-composition guard) into `event.key === 'å'`, silently changing behaviour. The commit went through green; it was caught only by re-reading the diff after committing.

## Possible Solution

Turn off `unicorn/prefer-keyboard-event-key` autofix (or the rule), or run oxlint without `--fix` in the hook so unsafe rewrites surface as errors.

## Minimal Reproducible Example

Stage a `.ts` file with `if (event.keyCode === 229) return;` and commit; inspect the committed diff.

## Context

229 is the keyCode browsers report while an IME composes; the rule maps it as a character code, but `event.key` there is `Process`, never `å`.
