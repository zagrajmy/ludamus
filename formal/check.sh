#!/usr/bin/env bash
# Check every Bend file a spec directory's `expected` file lists, with a pinned
# Bend. Usage: formal/check.sh formal/enrollment
set -euo pipefail

BEND_VERSION="2.0.37"

spec_dir="${1:?usage: formal/check.sh <spec dir>}"
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

failed=0
while read -r file kind why; do
  case "$file" in '' | '#'*) continue ;; esac
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
    finding) echo "GONE      $file: the witness no longer reproduces the bug" ;;
    *) echo "BROKEN    $file: unknown kind '$kind'" ;;
  esac
  while IFS= read -r line; do
    echo "          $line"
  done <<<"$out"
done <"$spec_dir/expected"

exit "$failed"
