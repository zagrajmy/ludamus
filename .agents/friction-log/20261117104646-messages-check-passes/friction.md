---
title: 'messages-check passes a catalog with a duplicate msgid that compilemessages rejects'
severity: 'minor'
---

### Expected Behavior

`mise run messages-check` fails when `django.po` holds the same msgid twice, as `compilemessages` does.

### Current Behavior

After merging main into a branch that had added the same msgid ("Encounter"), git kept both entries. `messages-check` and `mise run check` passed, and CI failed later in `test:e2e:prep`: msgfmt reported a duplicate message definition.

### Possible Solution

Run `msgfmt --check-format -o /dev/null` on the catalog (or `compilemessages`) inside `messages-check`.

### Minimal Reproducible Example

Copy any entry in `src/ludamus/locale/pl/LC_MESSAGES/django.po` to the end of the file, then run `mise run messages-check` (passes) and `mise run dj compilemessages -l pl` (fails).

### Context

Merging main into a feature branch on PR #1800.
