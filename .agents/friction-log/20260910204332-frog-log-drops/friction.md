---
title: 'Frog log drops the first line of piped bodies even with an explicit title'
severity: 'minor'
issue: 'zagrajmy/ludamus#1275'
---

## Expected Behavior

When the title is supplied as an argument, piping the complete Markdown body
preserves its first heading, as the --body help implies.

## Current Behavior

Frog 1.1.0 interprets the first nonempty input line as a title regardless of the
explicit title argument. A body starting with Expected Behavior loses that
heading and fails with BODY_DOES_NOT_MATCH_FORM.

## Possible Solution

Pass the body with --body, or put a title on the first line of stdin before the
body. The repository README uses the latter form.

## Minimal Reproducible Example

Pipe the five-section issue form starting with `## Expected Behavior` into
`mise run frog -- log 'An explicit title'`.

## Context

Observed while checking the noninteractive setup instructions on 2026-09-10.
