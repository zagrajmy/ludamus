---
title: 'ruff format rewrites hundreds of files the repo formats with Black'
severity: 'minor'
---

## Expected Behavior

Formatting new Python files with the obvious tool leaves untouched files alone.

## Current Behavior

`ruff format` restyled about 350 untouched files (hugged brackets, joined strings). The repo formats with Black and runs Ruff only as a linter.

## Possible Solution

Say in CLAUDE.md that Black formats Python (`mise run format:black`), or set `[tool.ruff.format]` to exclude everything.

## Minimal Reproducible Example

`.venv/bin/ruff format src tests` on a clean main checkout.

## Context

Hit while adding new modules; the diff had to be restored file by file.
