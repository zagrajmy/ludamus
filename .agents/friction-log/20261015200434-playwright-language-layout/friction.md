---
title: 'Playwright language layout checks need an explicit language cookie'
severity: 'minor'
---

## Expected Behavior

Setting Accept-Language to Polish should exercise the translated landing page.

## Current Behavior

The new Playwright layout checks still received English after page.setExtraHTTPHeaders({"Accept-Language": "pl"}), even with the Polish catalog compiled. Setting the django_language cookie before navigation selects Polish reliably.

## Possible Solution

Use a browser-context locale or explicit language cookie for localized E2E checks.

## Minimal Reproducible Example

Run the landing layout checks using an Accept-Language header instead of the django_language cookie.

## Context

Encountered while verifying the enrollment animation and print layout in English and Polish.
