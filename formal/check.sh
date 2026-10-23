#!/usr/bin/env bash
# Check every Bend file a spec directory's `expected` file lists, with a pinned
# Bend. Usage: formal/check.sh [formal/enrollment ...]; no argument checks every
# directory under formal/ that has an `expected` file.
# FORMAL_REGEN=1 rewrites the compiled `js` entries instead of comparing them.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  dirs=("$@")
  if [ "${#dirs[@]}" -eq 0 ]; then
    for expected in "$(dirname "$0")"/*/expected; do
      dirs+=("$(dirname "$expected")")
    done
  fi
  status=0
  for dir in "${dirs[@]}"; do
    echo "== $dir"
    "$0" "$dir" || status=1
  done
  exit "$status"
fi

BEND_VERSION="2.0.37"

spec_dir="$1"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/ludamus/bend-$BEND_VERSION"
bend="$cache_dir/bend/bin/bend"

# The sha256 of each release archive, as bend-lang.com/install.sh pins them.
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) platform=linux-x64 sum=84c32465a39bc9ac315eade23f470cb8db03153dc860f89564fcfec153c3e445 ;;
  Linux-aarch64) platform=linux-arm64 sum=b65d452e5c68a4c486e353220d4298ba5d76f535db47109a7d76ffdf72efafb1 ;;
  Darwin-arm64) platform=darwin-arm64 sum=846d25ccf0c12d5d1e5e648c0b3ba4c8397fdb852812ac00ef8135998f8e194b ;;
  Darwin-x86_64) platform=darwin-x64 sum=93eea3f54b7b91f28ea15a1b9f2d825afa58c1fcd417c11024a62f8c3506b813 ;;
  *)
    echo "ERROR: Bend has no release for $(uname -s)-$(uname -m)." >&2
    exit 2
    ;;
esac

sha256_ok() {
  if command -v sha256sum >/dev/null; then
    echo "$1  $2" | sha256sum --check --status
  else
    echo "$1  $2" | shasum -a 256 --check --status
  fi
}

if [ ! -x "$bend" ]; then
  archive="bend-$BEND_VERSION-$platform.tar.gz"
  url="https://github.com/bendlang/bend/releases/download/v$BEND_VERSION/$archive"
  rm -rf "$cache_dir"
  mkdir -p "$cache_dir"
  echo "Downloading Bend $BEND_VERSION to $cache_dir" >&2
  curl -sSfL --retry 4 -o "$cache_dir/$archive" "$url"
  if ! sha256_ok "$sum" "$cache_dir/$archive"; then
    echo "ERROR: $url does not match the pinned sha256." >&2
    rm -rf "$cache_dir"
    exit 2
  fi
  # The archives are built on macOS; GNU tar warns about their xattrs.
  tar_flags=()
  if tar --version 2>/dev/null | grep -q GNU; then
    tar_flags=(--warning=no-unknown-keyword)
  fi
  tar "${tar_flags[@]}" -xzf "$cache_dir/$archive" -C "$cache_dir"
  rm "$cache_dir/$archive"
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

failed=0
while read -r file kind why; do
  case "$file" in '' | '#'*) continue ;; esac
  if [ "$kind" = js ]; then
    source="${file%.gen.mjs}.bend"
    if [ "${FORMAL_REGEN:-}" = 1 ]; then
      (cd "$spec_dir" && BEND_NO_TELEMETRY=1 "$bend" "$source" -o "$file")
      echo "wrote     $file from $source"
    elif (cd "$spec_dir" && BEND_NO_TELEMETRY=1 "$bend" "$source" -o "$work_dir/$file") &&
      cmp -s "$work_dir/$file" "$spec_dir/$file"; then
      echo "ok        $file ($kind): $why"
    else
      echo "STALE     $file: not what $source compiles to; rerun with FORMAL_REGEN=1"
      failed=1
    fi
    continue
  fi
  set +e
  out="$(cd "$spec_dir" && BEND_NO_TELEMETRY=1 "$bend" "$file" 2>&1)"
  code=$?
  set -e
  if [ "$code" -eq 0 ] && grep -q '^ALL PROOFS CHECK' <<<"$out"; then
    echo "ok        $file ($kind): $why"
    continue
  fi
  failed=1
  case "$kind" in
    law) echo "BROKEN    $file: a law no longer has a proof" ;;
    finding) echo "GONE      $file: the witness no longer checks: the bug is fixed, or the model broke" ;;
    *) echo "BROKEN    $file: unknown kind '$kind'" ;;
  esac
  while IFS= read -r line; do
    echo "          $line"
  done <<<"$out"
done <"$spec_dir/expected"

exit "$failed"
