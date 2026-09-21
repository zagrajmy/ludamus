---
title: 'GitHub MCP strips screenshot embeds from PR descriptions'
severity: 'minor'
context:
  recorded_on: '2026-09-03'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 484
issue: 'zagrajmy/ludamus#1251'
---

## Expected Behavior

## Current Behavior

Posting a PR body through the GitHub MCP tool strips screenshot embeds:
'![alt](url)' comes back as '[alt](url)' and a raw <img> tag gets escaped into
inline code. CLAUDE.md asks for screenshots in the PR description, so they end
up as plain links only.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-03. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L484).

Historical observation; not reproduced as part of this migration.
