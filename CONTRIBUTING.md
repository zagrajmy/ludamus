# Contributing

Setup is in the [README](README.md). Architecture, conventions and testing
rules are in [CLAUDE.md](CLAUDE.md). `mise tasks` lists every command.

## Licensing

Ludamus is [AGPL-3.0-only](LICENSE), and contributions come in under the same
license. First-time contributors sign our [CLA](CLA.md); a bot posts the link on
your pull request and you accept in a comment. It takes a minute and covers
everything you contribute from then on.

**You keep your copyright.** The CLA is a licence, not a transfer. What it adds
beyond the AGPL is the right to sublicense, which is what lets the project be
relicensed or offered on commercial terms later without tracking down every
contributor. Without it, one unreachable person can freeze the licence forever.
We reconstructed the holder list from the commit log once; that doesn't scale.

Vendoring or adapting third-party code is fine, say so in the pull request. MIT,
BSD and Apache-2.0 are compatible; copyleft outside the GPL family usually
isn't.

## Before a pull request

Run `mise run check` and `mise run test:py`. CI runs the rest.

## Bugs

Open an issue. Security problems go to the address in the site footer instead.
