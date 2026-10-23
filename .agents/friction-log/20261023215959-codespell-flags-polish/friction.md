---
title: 'codespell flags Polish words in English docs'
severity: 'minor'
---

## Expected Behavior

A runbook for Polish authorities can quote Polish terms.

## Current Behavior

The codespell pre-commit hook rejected docs/POLICE_ESCALATION.md over 'numer sprawy' (Polish: case number) with 'numer ==> number'; I reworded around it.

## Possible Solution

Add Polish legal terms such as numer to the codespell ignore list.

## Minimal Reproducible Example

echo 'numer sprawy' > /tmp/x.md && codespell /tmp/x.md

## Context

Police escalation runbook (#1568).
