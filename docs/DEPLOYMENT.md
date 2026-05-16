# Deployment Guide

## 1. Local Development (No Docker)

**Prerequisites:** [mise](https://mise.jdx.dev/) installed.

```bash
# 1. Optional: drop personal overrides into .env.local (gitignored).
#    The committed .env carries dev defaults that work out of the box.
cp .env.docker .env.local  # only if you want to start from the docker baseline

# 2. Install toolchain (Python 3.14, Node v25.6.1, Poetry)
#    Re-run after Python/Node version bumps in mise.toml
mise install

# 3. Install Python dependencies
#    Re-run after pulling to sync lockfile changes
mise run p install

# 4. Run database migrations (if any new ones)
mise run dj migrate

# 5. Start dev server (Django + Tailwind watch on :8000)
mise run start
```

Uses SQLite by default (`USE_POSTGRES=false`). Set `DB_NAME` to a file path
(e.g. `db.sqlite3`). No PostgreSQL needed.

## 2. Local Docker Development

**Prerequisites:** Docker, mise (for the `dc` task wrapper).

```bash
# 1. Copy the Docker baseline into .env and fill in values
#    Important: set DB_HOST=db (the compose service name)
cp .env.docker .env.local

# 2. Build and start all services
mise run dc local up --build
```

**What happens automatically:**

- Builds the `dev` stage from `docker/Dockerfile`
- Mounts `src/` for live reload during development
- On startup runs: `migrate`, `createcachetable`, `downloadvendor`, then
  starts the dev server
- PostgreSQL 16 runs in a separate container with health checks
- Web is accessible at `http://localhost:8000`

**Source files:** `docker/compose/local.yaml`, `docker/Dockerfile` (target: `dev`)

## 3. Production Docker — New VPS

**Prerequisites:** Docker, Docker Compose, a reverse proxy (nginx/Caddy) for
HTTPS termination.

```bash
# 1. Create a dedicated user for the deployment
sudo useradd -m -s /bin/bash ludamus
sudo usermod -aG docker ludamus
sudo su - ludamus

# 2. Clone the repository
git clone <repo-url> && cd ludamus

# 3. Override the committed .env baseline with production values
#    Use .env.docker as a starting point, then set:
#    ENV=production, DEBUG=false, a real SECRET_KEY,
#    ALLOWED_HOSTS, Auth0 credentials, DB credentials, etc.
cp .env.docker .env.local
# Edit .env.local with production values (gitignored, layered on top of .env)

# 4. Create host directories for bind mounts
mkdir -p ~/ludamus/{postgres_data,static,media}

# 5. Set bind mount paths in .env.local
#    POSTGRES_DATA_PATH=/home/ludamus/ludamus/postgres_data
#    STATIC_DATA_PATH=/home/ludamus/ludamus/static
#    MEDIA_DATA_PATH=/home/ludamus/ludamus/media

# 6. Build and start production services
docker compose --env-file .env.local -f docker/compose/prod.yaml up -d --build
```

**Startup order** (enforced by `depends_on` with health checks):

1. `db` — PostgreSQL 16 starts, health check passes
2. `migrations` — runs `django-admin migrate` and `createcachetable`
3. `collectstatic` — runs `downloadvendor` and `collectstatic --noinput --clear`
4. `web` — Gunicorn (4 workers, 2 threads) listening on `127.0.0.1:8000`

**Reverse proxy required:** The web service binds to `127.0.0.1:8000` (not
publicly accessible). Place nginx or Caddy in front to handle HTTPS. Django is
pre-configured for production with:

- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
- `USE_X_FORWARDED_HOST = True`
- `USE_X_FORWARDED_PORT = True`

**Bind mount paths:** `POSTGRES_DATA_PATH`, `STATIC_DATA_PATH`, and
`MEDIA_DATA_PATH` in `.env` control where Docker volumes are stored on the
host. They default to `/var/lib/ludamus/` in `docker/compose/prod.yaml` but
should be set to the dedicated user's home directory as shown above.

**Source files:** `docker/compose/prod.yaml`, `docker/Dockerfile` (target: `prod`)

## 4. Upgrading Existing Production

```bash
git pull

# Rebuild and restart — migrations and collectstatic run automatically
docker compose --env-file .env.local -f docker/compose/prod.yaml up -d --build
```

Migrations run automatically via the `migrations` service. Static files are
re-collected via the `collectstatic` service.

If only env vars changed (no code changes):

```bash
docker compose --env-file .env.local -f docker/compose/prod.yaml up -d
```

## 5. Environment Variables Reference

Django variables are read in `src/ludamus/edges/settings.py`.
Docker Compose variables are read in `docker/compose/prod.yaml`.

Scopes: **L** = local, **D** = docker local, **P** = prod.

**Core** (all scopes):

- `ENV` — `local` or `production` *(required)* — L D P
- `SECRET_KEY` — Django secret key — L D P
- `DEBUG` — enable debug mode, default `false` — L D P
- `DJANGO_SETTINGS_MODULE` — settings path *(required)* — L D P

**Domain** (prod only):

- `ALLOWED_HOSTS` — comma-separated, default `localhost` — P
- `ROOT_DOMAIN` — root domain for the site — P
- `SESSION_COOKIE_DOMAIN` — cookie domain — P

**Database:**

- `USE_POSTGRES` — default `false` — L(opt) D P
- `DB_NAME` — database name or SQLite file path — L D P
- `DB_USER` — PostgreSQL user — L(pg) D P
- `DB_PASSWORD` — PostgreSQL password — L(pg) D P
- `DB_HOST` — PostgreSQL host (`db` in Docker) — L(pg) D P
- `DB_PORT` — PostgreSQL port — L(pg) D P

**Auth0** (all scopes):

- `AUTH0_CLIENT_ID` — application client ID — L D P
- `AUTH0_CLIENT_SECRET` — application client secret — L D P
- `AUTH0_DOMAIN` — tenant domain — L D P

**Static/Media files** (prod only):

- `GIT_COMMIT_SHA` — cache busting, default `1` — P(auto)
- `STATIC_ROOT` — collected static path — P(opt)
- `MEDIA_ROOT` — uploaded media path — P(opt)

**Membership API:**

- `MEMBERSHIP_API_BASE_URL` — external API URL — L(opt) D(opt) P
- `MEMBERSHIP_API_TOKEN` — API auth token — L(opt) D(opt) P
- `MEMBERSHIP_API_TIMEOUT` — timeout in seconds, default `30` — P(opt)
- `MEMBERSHIP_API_CHECK_INTERVAL` — minutes, default `15` — P(opt)

**Docker Compose** (prod only, from `prod.yaml`):

- `WEB_PORT` — host port for web service, default `8000` — P(opt)
- `POSTGRES_DATA_PATH` — default `/var/lib/ludamus/postgres_data` — P
- `STATIC_DATA_PATH` — default `/var/lib/ludamus/static` — P
- `MEDIA_DATA_PATH` — default `/var/lib/ludamus/media` — P

**Other:**

- `SUPPORT_EMAIL` — default `support@example.com` — L(opt) D(opt) P(opt)

## 6. Useful Commands Reference

```bash
# Docker Compose (via mise wrapper)
mise run dc local up          # Start local Docker dev
mise run dc local down        # Stop local Docker dev
mise run dc prod up --build   # Start/rebuild production
mise run dc prod down         # Stop production

# Local development
mise run start                # Django dev server + Tailwind watch (:8000)
mise run test                 # Run all tests
mise run check                # Format + lint (black, ruff, mypy, pylint, etc.)
mise run dj <command>         # Run any django-admin command
mise run build-frontend       # Build production CSS + JS

# Inside production container
mise run gunicorn             # Gunicorn (4 workers, 2 threads, :8000)
```
