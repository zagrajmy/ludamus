#!/usr/bin/env bash
# Explore the seeded e2e app with Bombadil, signed in as the party host, and
# check tests/bombadil/enrollment.ts on every state. Exits 2 on a violation.
# Run via `mise run test:bombadil`, which loads .env.e2e.
#   BOMBADIL_TIME_LIMIT  how long to explore (default 3m)
#   BOMBADIL_SKIP_PREP=1 reuse the database `mise run test:e2e:prep` made
#   BOMBADIL_ARGS        extra CLI options, e.g. for an older Chromium:
#                        --chrome-grant-permissions local-network-access
set -euo pipefail

BOMBADIL_VERSION="0.7.9"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/ludamus/bombadil-$BOMBADIL_VERSION"
bombadil="$cache_dir/bombadil"
event="kapitularz-2025-anonymized"

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) asset=bombadil-x86_64-linux sum=3af4ab33e0273de2455b54fd7bc687c8742b7411db86c965c3cd3de30f9d5cde ;;
  Darwin-arm64) asset=bombadil-aarch64-darwin sum=e81ea0390168544ce2d62ad591b554c320e3ceaeed3b78ee190f84787ccb85e2 ;;
  *)
    echo "ERROR: no pinned Bombadil for $(uname -s)-$(uname -m)." >&2
    exit 1
    ;;
esac

sha256_ok() {
  if command -v sha256sum >/dev/null; then
    echo "$1  $2" | sha256sum --check --status
  else
    echo "$1  $2" | shasum -a 256 --check --status
  fi
}

if [ ! -x "$bombadil" ]; then
  url="https://github.com/antithesishq/bombadil/releases/download/v$BOMBADIL_VERSION/$asset"
  mkdir -p "$cache_dir"
  echo "Downloading Bombadil $BOMBADIL_VERSION to $cache_dir" >&2
  curl -sSfL --retry 4 -o "$bombadil.part" "$url"
  if ! sha256_ok "$sum" "$bombadil.part"; then
    echo "ERROR: $url does not match the pinned sha256." >&2
    rm -f "$bombadil.part"
    exit 1
  fi
  chmod +x "$bombadil.part"
  mv "$bombadil.part" "$bombadil"
fi

cd "$repo_root"
if [ "${BOMBADIL_SKIP_PREP:-}" != 1 ]; then
  mise run test:e2e:prep
fi

mise run test:e2e:serve &
server=$!
trap 'mise run test:e2e:kill >/dev/null 2>&1 || kill "$server" 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
  curl -fsS -o /dev/null http://localhost:8000/ && break
  sleep 2
done

# A real session for a seeded user, so Bombadil starts signed in.
cookie="$(python - <<'PY'
import django

django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client

client = Client()
client.force_login(get_user_model().objects.get(username="e2e-party-host"))
print(f"{settings.SESSION_COOKIE_NAME}={client.cookies[settings.SESSION_COOKIE_NAME].value}")
PY
)"

# The boundary keeps exploration on the event's pages and the dashboard: the
# sign-in and sign-out links live under /crowd/, and the e2e login points at a
# placeholder Auth0 tenant that can only answer 500.
# `${extra[@]+...}` because Bash 3.2 (macOS) treats an empty array as unset
# under `set -u`.
read -r -a extra <<<"${BOMBADIL_ARGS:-}"
"$bombadil" browser test --headless --no-sandbox --exit-on-violation \
  --time-limit "${BOMBADIL_TIME_LIMIT:-3m}" \
  --output-path bombadil-output --output-path-overwrite \
  --cookie "$cookie" \
  --allow-url 'http://localhost/event/*' \
  --allow-url 'http://localhost/dashboard/*' \
  ${extra[@]+"${extra[@]}"} \
  "http://localhost:8000/event/$event/" tests/bombadil/enrollment.ts
