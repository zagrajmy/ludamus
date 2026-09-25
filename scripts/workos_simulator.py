"""A stand-in for the WorkOS AuthKit endpoints Zagrajmy calls, for offline dev.

Point `WORKOS_BASE_URL` at it and the WorkOS SDK sends the browser here to sign
in, redeems the code here, and ends the session here. It keeps no state: the
code carries the identity, so any running copy serves any worktree.

Never reachable in production: it binds to loopback and idles unless
`WORKOS_BASE_URL` names a loopback address.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import signal
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TypedDict
from urllib.parse import parse_qs, urlencode, urlsplit

from pydantic import TypeAdapter, ValidationError

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})
DEFAULT_EMAIL = "default@example.com"
DEFAULT_NAME = "Local Manager"


class _AuthenticateBody(TypedDict):
    code: str


_BODY = TypeAdapter(_AuthenticateBody)

_FORM = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>WorkOS simulator</title></head>
<body style="font-family: sans-serif; max-width: 24rem; margin: 4rem auto">
<h1>Sign in (WorkOS simulator)</h1>
<p>Any email signs in; a new one creates an account.</p>
<form method="get" action="/user_management/authorize/complete">
<input type="hidden" name="redirect_uri" value="{redirect_uri}">
<input type="hidden" name="state" value="{state}">
<p><label>Email<br>
<input name="email" type="email" value="{email}" required></label></p>
<p><label>Name<br><input name="name" value="{name}"></label></p>
<p><button type="submit">Sign in</button></p>
</form>
</body>
</html>
"""


def _first(query: dict[str, list[str]], key: str) -> str:
    return query.get(key, [""])[0]


def _is_local(url: str) -> bool:
    # parse_qs decodes %0d%0a, so a control character here would split the
    # Location header into a second, attacker-chosen one.
    if not url.isprintable():
        return False
    host = urlsplit(url).hostname or ""
    return host in LOOPBACK_HOSTS or host.endswith(".localhost")


def _segment(claims: dict[str, str]) -> str:
    raw = json.dumps(claims).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _user(*, email: str, name: str) -> dict[str, str | bool | None]:
    digest = hashlib.sha256(email.lower().encode()).hexdigest()[:20].upper()
    first, _, last = name.partition(" ")
    return {
        "object": "user",
        "id": f"user_SIM{digest}",
        "email": email,
        "email_verified": True,
        "first_name": first or None,
        "last_name": last or None,
        "profile_picture_url": None,
        "external_id": None,
        "last_sign_in_at": None,
        "created_at": "2026-01-01T00:00:00.000Z",
        "updated_at": "2026-01-01T00:00:00.000Z",
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        match parts.path:
            case "/user_management/authorize":
                self._authorize_form(query)
            case "/user_management/authorize/complete":
                self._complete(query)
            case "/user_management/sessions/logout":
                self._redirect(_first(query, "return_to"))
            case _:
                self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/user_management/authenticate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            code = _BODY.validate_json(self.rfile.read(length))["code"]
            identity = parse_qs(base64.urlsafe_b64decode(code + "==").decode())
        except ValidationError, ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_grant"})
            return
        if not (email := _first(identity, "email")):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_grant"})
            return
        session_id = f"session_SIM{secrets.token_hex(8).upper()}"
        self._json(
            HTTPStatus.OK,
            {
                "user": _user(email=email, name=_first(identity, "name")),
                "access_token": (
                    f"{_segment({'alg': 'none'})}.{_segment({'sid': session_id})}."
                ),
                "refresh_token": secrets.token_urlsafe(16),
                "authentication_method": "Password",
            },
        )

    def _authorize_form(self, query: dict[str, list[str]]) -> None:
        body = _FORM.format(
            redirect_uri=html.escape(_first(query, "redirect_uri")),
            state=html.escape(_first(query, "state")),
            email=DEFAULT_EMAIL,
            name=DEFAULT_NAME,
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _complete(self, query: dict[str, list[str]]) -> None:
        identity = urlencode(
            {"email": _first(query, "email"), "name": _first(query, "name")}
        )
        code = base64.urlsafe_b64encode(identity.encode()).rstrip(b"=").decode()
        params = urlencode({"code": code, "state": _first(query, "state")})
        self._redirect(f"{_first(query, 'redirect_uri')}?{params}")

    def _redirect(self, location: str) -> None:
        if not _is_local(location):
            self.send_error(HTTPStatus.BAD_REQUEST, "Redirects stay on localhost")
            return
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    base = urlsplit(os.environ.get("WORKOS_BASE_URL", ""))
    if base.hostname not in LOOPBACK_HOSTS or base.port is None:
        print(
            "[workos] WORKOS_BASE_URL is not a local http://localhost:<port>; "
            "simulator idle",
            file=sys.stderr,
        )
        signal.pause()
        return
    try:
        server = ThreadingHTTPServer(("127.0.0.1", base.port), _Handler)
    except OSError:
        # NOTE: stateless, so a copy another worktree started serves us too.
        print(f"[workos] :{base.port} is taken; using that simulator", file=sys.stderr)
        signal.pause()
        return
    print(
        f"[workos] simulator on {base.geturl()} (any email signs in)", file=sys.stderr
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
