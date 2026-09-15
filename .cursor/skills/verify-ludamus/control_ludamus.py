#!/usr/bin/env python3
"""Drive the local ludamus app for agent verification."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
TOKENS_PATH = REPO_ROOT / ".local" / "mcp-tokens.json"
RUN_PATH = REPO_ROOT / ".local" / "verify-ludamus-run.json"
EVIDENCE_DIR = REPO_ROOT / ".local" / "verify-ludamus" / "evidence"
HTTP_SCHEMES = ("http", "https")
HTTP_ORIGIN_PREFIXES = ("http://", "https://")
HTTP_OK = 200
UNPIN_SCROLL = (
    "const s=document.getElementById('app-scroll'); if(s){"
    "document.documentElement.style.height='auto';"
    "document.body.style.height='auto';"
    "document.body.style.overflow='visible';"
    "s.style.height='auto';s.style.overflow='visible';}"
)


def _ensure_django() -> None:
    src = REPO_ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ludamus.edges.settings")
    import django

    django.setup()


def _site_origin() -> str:
    from django.conf import settings
    from django.contrib.sites.models import Site

    site = Site.objects.filter(id=settings.SITE_ID).first()
    domain = site.domain if site is not None else settings.ROOT_DOMAIN
    if domain.startswith(HTTP_ORIGIN_PREFIXES):
        return domain.rstrip("/")
    return f"http://{domain}"


def _urlopen(request: urllib.request.Request, *, timeout: int) -> HTTPResponse:
    parsed = urlparse(request.get_full_url())
    if parsed.scheme not in HTTP_SCHEMES:
        message = f"Refusing non-http URL scheme {parsed.scheme!r}"
        raise ValueError(message)
    response = urllib.request.urlopen(request, timeout=timeout)
    if not isinstance(response, HTTPResponse):
        raise TypeError("expected an HTTP response")
    return response


def _probe(*, url: str, host: str | None = None) -> dict[str, Any]:
    parsed = urlparse(url)
    headers = {"Accept": "application/json"}
    if host:
        headers["Host"] = host
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with _urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
            header_map = {key.lower(): value for key, value in response.headers.items()}
            return {
                "url": url,
                "host": host or parsed.netloc,
                "status": response.status,
                "body": body,
                "portless": header_map.get("x-portless") == "1",
                "ok": response.status == HTTP_OK and '"status": "ok"' in body,
            }
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        header_map = {key.lower(): value for key, value in error.headers.items()}
        return {
            "url": url,
            "host": host or parsed.netloc,
            "status": error.code,
            "body": body[:300],
            "portless": header_map.get("x-portless") == "1",
            "ok": False,
        }
    except urllib.error.URLError as error:
        return {
            "url": url,
            "host": host or parsed.netloc,
            "status": 0,
            "body": str(error.reason),
            "portless": False,
            "ok": False,
        }


def _healthz(origin: str, *, host: str | None = None) -> dict[str, Any]:
    return _probe(url=f"{origin.rstrip('/')}/healthz/", host=host)


def _load_tokens() -> dict[str, Any] | None:
    if not TOKENS_PATH.exists():
        return None
    return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))


def _mcp_ping(*, origin: str, path: str, token: str) -> bool:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode()
    request = urllib.request.Request(
        urljoin(origin.rstrip("/") + "/", path.lstrip("/")),
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode())
        return body.get("result") == {}
    except urllib.error.URLError, json.JSONDecodeError:
        return False


def _sites() -> list[dict[str, Any]]:
    from django.contrib.sites.models import Site

    rows: list[dict[str, Any]] = []
    for site in Site.objects.order_by("id"):
        domain = site.domain
        origin = (
            domain.rstrip("/")
            if domain.startswith(HTTP_ORIGIN_PREFIXES)
            else f"http://{domain}"
        )
        rows.append(
            {"id": site.pk, "name": site.name, "domain": domain, "origin": origin}
        )
    return rows


def _probes(*, origin: str, sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed = urlparse(origin)
    probes = [
        _healthz(origin),
        _healthz("http://127.0.0.1:8000", host=parsed.netloc),
        _healthz("http://127.0.0.1:8000", host="localhost:8000"),
        _healthz("http://127.0.0.1:1355", host=parsed.netloc),
    ]
    seen = {parsed.netloc, "localhost:8000"}
    for site in sites:
        host = urlparse(str(site["origin"])).netloc
        if host and host not in seen:
            seen.add(host)
            probes.append(_healthz("http://127.0.0.1:8000", host=host))
    return probes


def _live_origin(*, origin: str, probes: list[dict[str, Any]]) -> str | None:
    if probes[0]["ok"]:
        return origin
    healthy = next((probe for probe in probes if probe["ok"]), None)
    if healthy is None:
        return None
    return f"http://{healthy['host']}"


def _mcp_report(*, origin: str | None, tokens: dict[str, Any] | None) -> dict[str, Any]:
    mcp: dict[str, Any] = {}
    if not origin or not tokens:
        return mcp
    maintainer = tokens.get("maintainer")
    if isinstance(maintainer, dict) and "token" in maintainer:
        mcp["maintainer_ping"] = _mcp_ping(
            origin=origin,
            path=str(maintainer.get("path", "/mcp/")),
            token=str(maintainer["token"]),
        )
    organizer = tokens.get("organizer")
    if isinstance(organizer, dict):
        mcp["organizer"] = {
            slug: _mcp_ping(
                origin=origin,
                path=str(row.get("path", "/mcp/organizer/")),
                token=str(row["token"]),
            )
            for slug, row in organizer.items()
            if isinstance(row, dict) and "token" in row
        }
    return mcp


def _advice(
    *,
    live_origin: str | None,
    tokens: dict[str, Any] | None,
    stale_portless: bool,
    origin: str,
    sites: list[dict[str, Any]],
) -> list[str]:
    lines: list[str] = []
    if live_origin is None:
        lines.append("Nothing healthy. Start with `mise run start`, then doctor again.")
    if tokens is None:
        lines.append("No .local/mcp-tokens.json. Run `mise run mcp-token`.")
    if stale_portless:
        lines.append(
            "Portless on :1355 answered without /healthz/. That is a stale proxy, "
            "not the app. Do not pkill portless; attach to the Site domain instead."
        )
    extra = [site for site in sites if site["origin"] != origin]
    if extra:
        hosts = ", ".join(str(site["origin"]) for site in extra)
        lines.append(
            "Public pages are hosted on the sphere Site, not always SITE_ID. "
            f"Also present: {hosts}. Open that origin for the matching event."
        )
    return lines


def doctor() -> dict[str, Any]:
    _ensure_django()
    from django.conf import settings

    origin = _site_origin()
    sites = _sites()
    probes = _probes(origin=origin, sites=sites)
    live_origin = _live_origin(origin=origin, probes=probes)
    tokens = _load_tokens()
    stale_portless = any(
        probe["portless"] and not probe["ok"] and probe["status"] != 0
        for probe in probes
    )
    organizer = (
        list(tokens["organizer"])
        if tokens and isinstance(tokens.get("organizer"), dict)
        else []
    )
    return {
        "ok": live_origin is not None,
        "base_url": live_origin,
        "site_origin": origin,
        "sites": sites,
        "db": str(settings.DATABASES["default"]["NAME"]),
        "tokens_path": str(TOKENS_PATH) if tokens else None,
        "organizer_events": organizer,
        "mcp": _mcp_report(origin=live_origin, tokens=tokens),
        "stale_portless": stale_portless,
        "probes": [
            {key: probe[key] for key in ("url", "host", "status", "ok", "portless")}
            for probe in probes
        ],
        "advice": _advice(
            live_origin=live_origin,
            tokens=tokens,
            stale_portless=stale_portless,
            origin=origin,
            sites=sites,
        ),
    }


def _require_base() -> str:
    report = doctor()
    if not report["ok"] or not report["base_url"]:
        raise SystemExit("Instance is not healthy.\n" + "\n".join(report["advice"]))
    return str(report["base_url"])


def _write_run(*, mode: str, pid: int | None, base_url: str) -> None:
    RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_PATH.write_text(
        json.dumps({"mode": mode, "pid": pid, "base_url": base_url}, indent=2) + "\n",
        encoding="utf-8",
    )


def cmd_launch() -> int:
    report = doctor()
    if report["ok"] and report["base_url"]:
        _write_run(mode="attach", pid=None, base_url=str(report["base_url"]))
        print(json.dumps({"mode": "attach", **report}, indent=2))
        return 0
    print(
        "No healthy instance. Start one in another terminal:\n"
        "  mise run start\n"
        "Do not reuse `mise run kill` / test:e2e:kill — those kill by port and "
        "will take the user's server. Doctor again after start.",
        file=sys.stderr,
    )
    print(json.dumps(report, indent=2))
    return 1


def cmd_cleanup() -> int:
    if not RUN_PATH.exists():
        print(json.dumps({"cleaned": False, "reason": "no run file"}))
        return 0
    state = json.loads(RUN_PATH.read_text(encoding="utf-8"))
    if state.get("mode") == "started" and state.get("pid"):
        os.kill(int(state["pid"]), 15)
        print(json.dumps({"cleaned": True, "killed_pid": state["pid"]}))
    else:
        print(
            json.dumps(
                {
                    "cleaned": True,
                    "mode": state.get("mode"),
                    "note": "attached instance left running",
                }
            )
        )
    return 0


def _browser(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["aubx", "agent-browser", *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _resolve_url(target: str) -> str:
    if target.startswith(HTTP_ORIGIN_PREFIXES):
        return target
    return urljoin(_require_base().rstrip("/") + "/", target.lstrip("/"))


def cmd_open(target: str) -> int:
    url = _resolve_url(target)
    result = _browser("open", url)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return 0


def cmd_snapshot(path: str | None = None) -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = Path(path) if path else EVIDENCE_DIR / "snapshot.txt"
    if not dest.is_absolute():
        dest = EVIDENCE_DIR / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = _browser("snapshot")
    dest.write_text(result.stdout, encoding="utf-8")
    print(result.stdout, end="")
    print(json.dumps({"path": str(dest)}))
    return 0


def cmd_screenshot(path: str | None) -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = Path(path) if path else EVIDENCE_DIR / "screenshot.png"
    if not dest.is_absolute():
        dest = EVIDENCE_DIR / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(subprocess.CalledProcessError):
        _browser("eval", UNPIN_SCROLL)
    result = _browser("screenshot", "--full", str(dest))
    print(result.stdout, end="")
    print(json.dumps({"path": str(dest)}))
    return 0


def cmd_browser(args: list[str]) -> int:
    result = _browser(*args)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return 0


def _organizer_row(tokens: dict[str, Any], *, event: str | None) -> dict[str, Any]:
    organizer = tokens.get("organizer")
    if not isinstance(organizer, dict) or not organizer:
        raise SystemExit("No organizer tokens. Run `mise run mcp-token`.")
    if event:
        row = organizer.get(event)
        if not isinstance(row, dict):
            known = ", ".join(organizer)
            message = f"No organizer token for {event!r}. Have: {known}"
            raise SystemExit(message)
        return row
    if len(organizer) == 1:
        return next(iter(organizer.values()))
    raise SystemExit(
        "Several organizer tokens; pass --event <slug>. Have: " + ", ".join(organizer)
    )


def cmd_mcp(*, scope: str, event: str | None, tool: str, arguments: str) -> int:
    report = doctor()
    if not report["ok"] or not report["base_url"]:
        raise SystemExit("Instance is not healthy; run doctor.")
    tokens = _load_tokens()
    if tokens is None:
        raise SystemExit("No .local/mcp-tokens.json. Run `mise run mcp-token`.")
    if scope == "maintainer":
        row = tokens["maintainer"]
        if not isinstance(row, dict):
            raise SystemExit("maintainer token payload is not an object")
    else:
        row = _organizer_row(tokens, event=event)
    try:
        parsed_args = json.loads(arguments)
    except json.JSONDecodeError as error:
        message = f"arguments must be JSON: {error}"
        raise SystemExit(message) from error
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": parsed_args},
        }
    ).encode()
    url = urljoin(
        str(report["base_url"]).rstrip("/") + "/", str(row["path"]).lstrip("/")
    )
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {row['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _urlopen(request, timeout=60) as response:
            print(response.read().decode())
    except urllib.error.HTTPError as error:
        raise SystemExit(error.read().decode()) from error
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive the local ludamus app for agent verification."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="Is this instance worth driving?")
    sub.add_parser("base-url", help="Print the live origin")
    sub.add_parser("launch", help="Attach to a healthy instance; refuse to hijack")
    sub.add_parser("cleanup", help="Tear down only what launch started")
    open_cmd = sub.add_parser("open", help="Open a path or URL in agent-browser")
    open_cmd.add_argument("target")
    snap = sub.add_parser("snapshot", help="Accessibility snapshot of the current page")
    snap.add_argument("path", nargs="?")
    shot = sub.add_parser("screenshot", help="Full-page screenshot into evidence/")
    shot.add_argument("path", nargs="?")
    browser = sub.add_parser("browser", help="Pass args through to agent-browser")
    browser.add_argument("args", nargs=argparse.REMAINDER)
    find_cmd = sub.add_parser("find", help="Find by ARIA role/name and act")
    find_cmd.add_argument("locator")
    find_cmd.add_argument("value")
    find_cmd.add_argument("action", nargs="?", default="click")
    find_cmd.add_argument("--name", default=None)
    mcp_cmd = sub.add_parser(
        "mcp", help="Call an MCP tool (seed/inspect, not UI proof)"
    )
    mcp_cmd.add_argument(
        "--scope", choices=("maintainer", "organizer"), default="organizer"
    )
    mcp_cmd.add_argument("--event", default=None)
    mcp_cmd.add_argument("tool")
    mcp_cmd.add_argument("arguments", nargs="?", default="{}")
    return parser


def cmd_doctor() -> int:
    report = doctor()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_base_url() -> int:
    print(_require_base())
    return 0


def cmd_find(*, locator: str, value: str, action: str, name: str | None) -> int:
    args = ["find", locator, value, action]
    if name:
        args.extend(["--name", name])
    return cmd_browser(args)


def cmd_browser_from_args(args: argparse.Namespace) -> int:
    forwarded = list(args.args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    return cmd_browser(forwarded)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "doctor": cmd_doctor,
        "base-url": cmd_base_url,
        "launch": cmd_launch,
        "cleanup": cmd_cleanup,
        "open": lambda: cmd_open(args.target),
        "snapshot": lambda: cmd_snapshot(args.path),
        "screenshot": lambda: cmd_screenshot(args.path),
        "browser": lambda: cmd_browser_from_args(args),
        "find": lambda: cmd_find(
            locator=args.locator, value=args.value, action=args.action, name=args.name
        ),
        "mcp": lambda: cmd_mcp(
            scope=args.scope, event=args.event, tool=args.tool, arguments=args.arguments
        ),
    }
    handler = commands.get(args.cmd)
    if handler is None:
        message = f"unhandled command {args.cmd}"
        raise SystemExit(message)
    return handler()


if __name__ == "__main__":
    raise SystemExit(main())
