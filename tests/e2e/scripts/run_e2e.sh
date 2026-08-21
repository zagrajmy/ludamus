#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

# The pinned @playwright/test the specs import sits in tests/e2e's
# optionalDependencies, which `mise run pr-fix` prunes (aube install
# --no-optional). test:e2e:prep reinstalls it, but prep runs inside
# Playwright's own webServer command — under the runner that already needs the
# package — so from a pruned tree the runner either cannot start or has the
# package swapped underneath it and every spec dies on "two different versions
# of @playwright/test". Restore the deps before the runner starts; it is a
# no-op on an installed tree.
(cd "$repo_root" && aube install)

npx playwright test "$@"
coverage report --rcfile="$repo_root/pyproject.toml"
