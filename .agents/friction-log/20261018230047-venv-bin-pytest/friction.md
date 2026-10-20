---
title: '`.venv/bin/pytest` on one file fails with "No module named ludamus"'
severity: 'minor'
---

## Expected Behavior

Running pytest on one test file from the venv runs it, or the error says to use `mise run test:py`.

## Current Behavior

`.venv/bin/pytest tests/integration/web/chronology/<file>.py` stops in pytest-django with `ImportError: No module named 'ludamus'` and "could not find a Django project (no manage.py file)". `PYTHONPATH=src` and `.env.test` come only from mise.

## Possible Solution

Set `pythonpath = ["src"]` in the pytest config, or have the conftest point at `mise run test:py`.

## Minimal Reproducible Example

`.venv/bin/pytest tests/integration/web/chronology/test_waitlist_promotion.py -n 0` fails; `mise run test:py -- -n 0 tests/integration/web/chronology/test_waitlist_promotion.py` works.

## Context

Cost one retry while reproducing an enrollment double-booking found by the TLA+ model.
