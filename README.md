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
mise run bootstrap      # .env, deps, migrations, demo data — idempotent
mise run start          # Django :8000 + Vite :5173
```

After bootstrap, log in at <http://localhost:8000/admin/> as `admin` / `admin`.

`mise run bootstrap` is safe to re-run any time — it tops up missing deps and
seed data without destroying anything.

### Day-to-day

```bash
mise run test           # all tests
mise run check          # format + lint + autofix
mise run prcheck        # CI-style lint, no autofix
mise tasks              # list every task with descriptions
```

Frontend lives in `src/ludamus/client/` (Vite + Tailwind). Architecture and
contributor conventions are documented in [CLAUDE.md](CLAUDE.md) (also
available as `AGENTS.md` for Cursor/OpenAI agents).

### Email in development

Outgoing email is configured by the `EMAIL_URL` env var (django-environ):

- `consolemail://` — default; prints emails to the server log.
- `smtp://mailpit:1025` — wired automatically in `mise run dc local`; view the
  captured inbox at <http://127.0.0.1:8025> (Mailpit). Best for end-to-end
  testing of enrollment/offer notifications.
- `filemail:///path/to/dir` — writes each email to a file.

Production sets `EMAIL_URL=smtp://user:pass@host:587/?tls=True`.

### Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
