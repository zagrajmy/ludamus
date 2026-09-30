---
title: 'Impeccable updater reports bundle verification 404 for published release'
severity: 'minor'
target: 'pbakaus/impeccable'
---

Running `npx impeccable update` and the v4.3.1 vendored launcher `impeccable check` fails with `Could not verify skill bundle: HTTP 404`, though GitHub release `skill-v4.3.1` publishes `universal.zip` and its signature (both return HTTP 200). We verified the published release SHA-256 and replaced the vendored skill from the archive directly. The updater should resolve and verify the published release assets or report the exact failing URL.
