---
title: 'htmx hx-get on a form with a required field silently skips the request'
severity: 'minor'
---

### Expected Behavior

A form with `hx-get` and `hx-trigger="change"` asks the server for a fresh preview whenever a radio changes.

### Current Behavior

htmx 2 validates the whole form first and halts (`htmx:validation:halted`) while a required textarea is still empty. Nothing reaches the server and the console shows no error; only `htmx.logAll()` revealed it.

### Possible Solution

Put the `hx-*` attributes on a `display: contents` wrapper inside the form with `hx-include="closest form"`, as `templates/staff/cases.html` now does.

### Minimal Reproducible Example

`<form hx-get="." hx-trigger="change"><input type="radio" name="a"><textarea required name="b"></textarea></form>`: checking the radio sends nothing.

### Context

Staff inbox decision preview; the e2e failed with no request in the server log.
