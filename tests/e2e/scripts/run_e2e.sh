#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

npx playwright test "$@"
coverage report --rcfile="$repo_root/pyproject.toml"
