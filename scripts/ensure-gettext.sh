#!/usr/bin/env bash
set -euo pipefail

gettext_ok() {
  command -v msgfmt >/dev/null && msgfmt --version | grep -q '(GNU gettext-tools) 1\.'
}

if gettext_ok; then
  exit 0
fi

if [ "$(uname -s)" = Darwin ]; then
  for prefix in /opt/homebrew/opt/gettext /usr/local/opt/gettext; do
    if [ -x "${prefix}/bin/msgfmt" ]; then
      export PATH="${prefix}/bin:${PATH}"
      if gettext_ok; then
        exit 0
      fi
    fi
  done
  echo "GNU gettext 1.0 required — install with: brew install gettext" >&2
  exit 1
fi

deb=/tmp/gettext_1.0-1_amd64.deb
curl -fsSL -o "${deb}" http://ftp.debian.org/debian/pool/main/g/gettext/gettext_1.0-1_amd64.deb
sudo apt-get install -y "${deb}"

if ! gettext_ok; then
  echo "GNU gettext 1.0 required after install — msgfmt: $(command -v msgfmt || echo missing)" >&2
  msgfmt --version >&2 || true
  exit 1
fi
