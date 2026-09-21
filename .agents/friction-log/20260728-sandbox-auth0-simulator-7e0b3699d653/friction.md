---
title: 'Sandbox Auth0 simulator needs manually provisioned valid CA certificates'
severity: 'minor'
context:
  recorded_on: '2026-07-28'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 111
issue: 'zagrajmy/ludamus#1189'
---

## Expected Behavior

## Current Behavior

auth0-simulator stays disabled in the sandbox until you hand-roll ~/.portless
certs, and Python 3.14 rejects a bare self-signed CA without
keyUsage=keyCertSign, so the first cert attempt failed with
CERTIFICATE_VERIFY_FAILED.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-28. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L111).

Historical observation; not reproduced as part of this migration.
