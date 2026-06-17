# ludamus

Event management website

[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Code style: djLint](https://img.shields.io/badge/html%20style-djLint-blue.svg)](https://github.com/djlint/djlint)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![linting: pylint](https://img.shields.io/badge/linting-pylint-yellowgreen)](https://github.com/pylint-dev/pylint)
![Static Badge](https://img.shields.io/badge/type%20checked-mypy-039dfc)
[![codecov](https://codecov.io/github/zagrajmy/ludamus/graph/badge.svg?token=DB3HZP1OWT)](https://codecov.io/github/zagrajmy/ludamus)

## Development

Requires [mise](https://mise.jdx.dev) — it manages Python, Node, Poetry, and the
project tasks.

```bash
mise install            # Python, Node, Poetry, ast-grep
mise bootstrap      # .env, deps, migrations, demo data — idempotent
mise dev                # Django :8000 + Vite :5173
```

After bootstrap, log in at <http://localhost:8000/admin/> as `admin` / `admin`.

`mise run bootstrap` resets and reseeds the local database with the same
deterministic data used by end-to-end tests.

### Day-to-day

```bash
mise test               # all tests
mise check              # format + lint + autofix
mise prcheck            # CI-style lint, no autofix
mise tasks              # list every task with descriptions
```

Frontend lives in `src/ludamus/client/` (Vite + Tailwind). Architecture and
contributor conventions are documented in [CLAUDE.md](CLAUDE.md) (also available
as `AGENTS.md` for Cursor/OpenAI agents).

### Email in development

Outgoing email is configured by the `EMAIL_URL` env var (django-environ):

- `consolemail://` — default; prints emails to the server log.
- `filemail:///path/to/dir` — writes each email to a file. Handy for
  end-to-end testing of enrollment/offer notifications: point the server at a
  directory and assert on the written `.log` files.

Production sets `EMAIL_URL=smtp://user:pass@host:587/?tls=True`.

### Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
