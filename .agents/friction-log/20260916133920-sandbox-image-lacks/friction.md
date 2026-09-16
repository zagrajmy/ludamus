---
title: 'Sandbox image lacks GNU gettext, so `mise run messages` cannot extract strings'
severity: 'minor'
---

## Expected Behavior

`mise run messages` re-extracts `django.po` in a Claude Code web sandbox the same way it does on a laptop.

## Current Behavior

`mise run messages` first fails on varlock (no `SECRET_KEY` etc. outside a task env), and running `django-admin makemessages` directly with `.env.test` sourced fails with "Can't find msguniq. Make sure you have GNU gettext tools 0.19 or newer installed." The image ships only `pygettext3`. `apt-get install gettext` fixes it (apt is reachable through the proxy).

## Possible Solution

Have `.claude/hooks/session-start.sh` apt-install `gettext` next to python3.14 and pipx, so the catalog task works out of the box.

## Minimal Reproducible Example

```sh
which msguniq        # nothing
mise run messages    # varlock validation error, then (with env) msguniq missing
```

## Context

Every UI change touches the catalog; without gettext the `messages-check` CI gate can only be satisfied by installing the tool by hand each session.
