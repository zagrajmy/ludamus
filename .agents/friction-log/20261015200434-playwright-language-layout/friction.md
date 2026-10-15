---
title: 'Localized E2E checks need compiled translation catalogs'
severity: 'minor'
---

## Expected Behavior

Fresh E2E preparation should serve both English and Polish without manual setup.

## Current Behavior

Polish landing-page locators failed in CI because E2E preparation did not compile
the translation catalog. Adding compilation exposed a second setup gap: the E2E
runners had not installed the declared GNU gettext package, so `msgfmt` was missing.
Local verification had succeeded after manually compiling the catalog.

## Possible Solution

Apply the declared bootstrap packages during E2E preparation, then compile the
Polish catalog before starting the server.

## Minimal Reproducible Example

Run the Polish landing-layout checks from a fresh checkout without `django.mo`.
The initial failure is in [the E2E workflow](https://github.com/zagrajmy/ludamus/actions/runs/38787341655);
the missing-compiler failure is in [this shard](https://github.com/zagrajmy/ludamus/actions/runs/38790097935/job/116612122136).

## Context

Encountered while verifying the enrollment animation and print layout in both
languages. A language cookie selects a locale but cannot supply its compiled catalog.
