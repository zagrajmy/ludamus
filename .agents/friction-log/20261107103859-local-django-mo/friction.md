---
title: 'Local django.mo hides a missing polish_catalog fixture in Python tests'
severity: 'minor'
---

### Expected Behavior

An integration test that asserts Polish text fails locally the same way it fails in CI.

### Current Behavior

It passes locally and fails in CI's `test-unit` job. A compiled, gitignored `django.mo` sits in the local tree, but CI never runs `compilemessages`, so the test reads English.

### Possible Solution

Use the `polish_catalog` fixture (`tests/integration/conftest.py`) in any test that reads Polish. A lint rule or a conftest guard could ignore the in-tree `.mo` during tests.

### Minimal Reproducible Example

Move `src/ludamus/locale/pl/LC_MESSAGES/django.mo` aside and run a test asserting `"Twoje bilety na …"` without `polish_catalog`.

### Context

Added a test that an account buyer's ticket mail is in their language (PR #1562); CI went red on a check that passed locally.
