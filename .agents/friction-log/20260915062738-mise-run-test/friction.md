---
title: '`mise run test:py` buries an assertion failure under hundreds of DEBUG log lines'
severity: 'minor'
---

## Expected Behavior

A failing test's traceback and `E` assertion lines are the first thing in the
failure section, so a single `tail` shows what broke.

## Current Behavior

`mise run test:py -- tests/integration/web/panel/test_panel_export.py -q` on a
failing test prints the captured log at DEBUG level: dozens of `faker.factory`
provider-localization lines, `factory.generate` LazyAttribute lines, and
Django's `VariableDoesNotExist` debug traces for every `|default` template
lookup. The real `AssertionError` sits several screens above them, so reading
the failure needs a second run with `grep -A25 "^E "`.

## Possible Solution

Raise the captured log level for the test run (`log_level = INFO` in the
pytest config, or silence `faker.factory` and `factory.generate` loggers), and
keep the `django.template` logger at INFO so default-filter misses stay quiet.

## Minimal Reproducible Example

Make any integration test in `tests/integration/web/panel/` fail an
`assert_response(..., context_data=...)` check and run
`mise run test:py -- <that file> -q`.

## Context

Reading two failures during plan 020 needed two extra test runs each, about a
minute apiece, just to find the assertion diff.
