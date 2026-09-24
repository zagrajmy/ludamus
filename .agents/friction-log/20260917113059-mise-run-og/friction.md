---
title: '`mise run og-image` rewrites the card at a different file size from unchanged source'
severity: 'minor'
issue: 'zagrajmy/ludamus#1314'
---

## Expected Behavior

`mise run og-image` on an unedited card leaves
`src/ludamus/static/og-image.jpg` byte-identical, so re-running the task is a
safe no-op and any diff means the card really changed.

## Current Behavior

It rewrites the file at a visibly different size — 162.6 KiB against the
committed 182 KiB — from identical input. The render is not reproducible across
environments; most likely the Chromium revision or font rendering differs
between the sandbox image and whoever last ran it.

## Possible Solution

Pin the Chromium revision the task renders with, or run the task in CI and fail
when the output drifts from the committed file.

## Minimal Reproducible Example

```sh
md5sum src/ludamus/static/og-image.jpg
mise run og-image          # no edit to scripts/og-image/card/
md5sum src/ludamus/static/og-image.jpg   # differs; 162.6 KiB vs 182 KiB
```

## Context

Hit while checking the build still worked after moving the card source out of
`src/ludamus/static/` in #1313. Cost me a `git checkout` to keep an unrelated
re-render out of the diff, after first suspecting my own change had broken the
build. The standing cost: anyone who edits the card and re-runs the task ships
a different-weight file, and a reviewer cannot tell an intended card change
from encoder drift.
