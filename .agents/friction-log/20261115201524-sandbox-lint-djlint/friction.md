---
title: 'Sandbox lint:djlint fails silently: djlint_underscore_end plugin not on PYTHONPATH'
severity: 'minor'
---

### Expected Behavior

`mise run lint:djlint` lints the templates in a Claude web sandbox.

### Current Behavior

It prints only `ERROR task failed`. `--quiet` hides the cause: `ModuleNotFoundError: No module named 'djlint_underscore_end'`.

### Possible Solution

Put `scripts/` on `PYTHONPATH` in the task, or in the sandbox setup.

### Minimal Reproducible Example

`mise run lint:djlint` fails; `PYTHONPATH=scripts djlint src --quiet --lint --check --format-css --format-js --profile=django` passes.

### Context

Found while linting the organize dialog templates.
