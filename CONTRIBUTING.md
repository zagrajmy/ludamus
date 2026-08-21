# Contributing

Setup is in the [README](README.md). Architecture, conventions and testing
rules are in [CLAUDE.md](CLAUDE.md). `mise tasks` lists every command.

## Licensing

Ludamus is [AGPL-3.0-only](LICENSE), and contributions come in under the same
license. By opening a pull request you confirm you wrote the code or have the
right to submit it, and that you license it under AGPL-3.0-only.

You keep your copyright. There is no CLA.

This is written down because relicensing needs every copyright holder's
agreement, and a project that never recorded who those are has to work it out
from the commit log afterwards. We did that once already.

Vendoring or adapting third-party code is fine, say so in the pull request. MIT,
BSD and Apache-2.0 are compatible; copyleft outside the GPL family usually
isn't.

## Before a pull request

Run `mise run check` and `mise run test:py`. CI runs the rest.

## Bugs

Open an issue. Security problems go to the address in the site footer instead.
