#!/usr/bin/env bash

# Flag suspicious additions vs main, reporting file:line for each hit.
#
# Usage: shitcheck.sh REGEX PATH [PATH...]
#
#   REGEX   POSIX ERE (awk flavour) matched against each added line.
#   PATH    one or more git pathspecs to scan, e.g. ':(glob)src/**/*.py'.
#
# Import lines (`from x import y`) are ignored unless they carry a comment (#),
# so e.g. a `# noqa` on an import is still flagged. Compose per-area rules by
# calling this once per path set with a different REGEX (see the shitcheck task).
#
# Note: the system awk is mawk, which has no \< \> \b word boundaries — emulate
# them with (^|[^[:alnum:]_])word([^[:alnum:]_]|$).

set -euo pipefail

pattern="$1"
shift

git diff main --unified=0 -- "$@" | awk -v pattern="$pattern" '
  /^\+\+\+ / { file = substr($0, 7); next }
  /^@@ /     { match($0, /\+[0-9]+/); line = substr($0, RSTART+1, RLENGTH-1) + 0; next }
  /^\+/ {
    body = substr($0, 2)
    if (body ~ /^[[:space:]]*(from|import)[[:space:]]/ && body !~ /#/) { line++; next }
    if (body ~ pattern) printf "%s:%d:%s\n", file, line, body
    line++
  }
'
