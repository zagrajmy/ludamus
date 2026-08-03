# Contributing

Thanks for wanting to help. This file covers licensing and the few things a
patch needs before it can be merged. Everything else — architecture, naming,
testing strategy — lives in [CLAUDE.md](CLAUDE.md), which applies to humans and
agents alike.

## Licensing of contributions

**Ludamus is [AGPL-3.0-only](LICENSE), and contributions are accepted under that
same license.** By opening a pull request you confirm that:

- you wrote the contribution, or otherwise have the right to submit it;
- you license it to the project under AGPL-3.0-only; and
- you understand it will be published as part of a network-available service,
  which under AGPL §13 means its source is offered to that service's users.

We ask this explicitly because a license is hard to change later: relicensing
needs the agreement of everyone holding copyright in the code, and a project
that never recorded who that is has to reconstruct it from commit history.
Stating it once, here, is what keeps that answerable.

You keep the copyright in your work. There is no CLA and no copyright
assignment — nobody gets rights to your contribution that the AGPL doesn't
already give every user.

Third-party code carries its own terms. If you vendor or adapt something, say so
in the pull request and check that its license is compatible with AGPL-3.0-only
— permissive licenses (MIT, BSD, Apache-2.0) generally are; copyleft licenses
other than the GPL family generally are not.

## Getting set up

[mise](https://mise.jdx.dev) manages the toolchain, dependencies and every task.

```bash
mise install            # Python, Node, Poetry, ast-grep
mise run bootstrap      # .env, deps, migrations, demo data — idempotent
mise dev                # Django :8000 + Vite :5173
mise tasks              # everything else, with descriptions
```

`mise tasks` is the source of truth for what you can run — prefer it over any
list written down elsewhere, including this one.

[docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) covers simulator login, Playwright auth
state, and the task-file tools.

## Before you open a pull request

```bash
mise run check          # format + lint (what CI's `checks` job runs)
mise run test:py        # unit + integration
mise run test:e2e       # Playwright, needs `mise run test:e2e:prep` first
```

A few expectations CI enforces, worth knowing before it tells you:

- **Strings are translatable.** User-facing text goes through `{% translate %}`
  or `{% blocktranslate %}`, and the Polish catalog must be current —
  `mise run messages` after changing strings, then commit the `.po`.
  `mise run messages-check` fails on stale, fuzzy or untranslated entries.
- **Tests follow the layer.** `mills` gets unit tests; `gates`, `links`,
  `adapters.web` and templates get integration tests; rendered HTML is asserted
  in `tests/e2e`. See [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md).
- **Schema changes ship a reversible migration.**
- **Debt is measured.** `tingle check` fails when a branch adds suppression
  comments, `Any`, or legacy LOC on net. A justified addition is fine — say so
  in the pull request rather than working around the counter.
- **UI changes include screenshots.** With a server running,
  `mise run shots -- / /events` writes PNGs to `screenshots/`.

## Reporting bugs and asking for features

Open an issue. For a bug, the useful shape is what you did, what happened, and
what you expected — plus the sphere and event if it's specific to one. Security
issues are the exception: mail them to the address in the site footer instead of
filing publicly.
