---
title: 'Sandbox mise 2026.10.25 refuses hk''s workflow option under the cargo alias'
severity: 'major'
---

### Expected Behavior

mise tasks run in a Claude web sandbox (MISE_ENV=sandbox).

### Current Behavior

Every `mise run` dies on `hk: option `workflow` is not used by the cargo backend`.

### Possible Solution

Override hk in mise.sandbox.toml without the `workflow` option, or drop it from the alias path.

### Minimal Reproducible Example

`mise run build-frontend` in a fresh sandbox.

### Context

mise.toml pins `hk = { version = "2.7.0", workflow = "release.yml" }`; mise.sandbox.toml aliases hk to `cargo:hk`. Worked around with `MISE_DISABLE_TOOLS=hk`.
