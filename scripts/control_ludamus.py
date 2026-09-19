#!/usr/bin/env python3
"""Drive the local ludamus app for agent verification."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import requests

from scripts.django_boot import boot_django
from scripts.mcp_token_file import (
    MaintainerToken,
    OrganizerToken,
    TokenFile,
    load_token_file,
)

if TYPE_CHECKING:
    from django.conf import Settings
    from django.contrib.sites.models import Site

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKENS_PATH = REPO_ROOT / ".local" / "mcp-tokens.json"
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


def _django_settings() -> Settings:
    boot_django()
    return import_module("django.conf").settings


def _site_model() -> type[Site]:
    boot_django()
    return import_module("django.contrib.sites.models").Site


def _site_origin() -> str:
    settings = _django_settings()
    site = _site_model().objects.filter(id=settings.SITE_ID).first()
    domain = site.domain if site is not None else settings.ROOT_DOMAIN
    if domain.startswith(HTTP_ORIGIN_PREFIXES):
        return domain.rstrip("/")
    return f"http://{domain}"


def _request(
    *,
    url: str,
    method: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    json_body: dict[str, object] | None = None,
) -> requests.Response:
    parsed = urlparse(url)
    if parsed.scheme not in HTTP_SCHEMES:
        message = f"Refusing non-http URL scheme {parsed.scheme!r}"
        raise ValueError(message)
    return requests.request(
        method, url, timeout=timeout, headers=headers, json=json_body
    )


def _probe(*, url: str, host: str | None = None) -> dict[str, object]:
    parsed = urlparse(url)
    headers = {"Accept": "application/json"}
    if host:
        headers["Host"] = host
    try:
        response = _request(url=url, method="GET", timeout=5, headers=headers)
    except requests.RequestException as error:
        return {
            "url": url,
            "host": host or parsed.netloc,
            "status": 0,
            "body": str(error),
            "portless": False,
            "ok": False,
        }
    return {
        "url": url,
        "host": host or parsed.netloc,
        "status": response.status_code,
        "body": response.text,
        "portless": response.headers.get("X-Portless") == "1",
        "ok": response.status_code == HTTP_OK and '"status": "ok"' in response.text,
    }


def _healthz(origin: str, *, host: str | None = None) -> dict[str, object]:
    return _probe(url=f"{origin.rstrip('/')}/healthz/", host=host)


def _sites() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for site in _site_model().objects.order_by("id"):
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


def _mcp_rpc(
    *,
    origin: str,
    path: str,
    token: str,
    method: str,
    params: dict[str, object] | None = None,
    timeout: int,
) -> object:
    payload: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    response = _request(
        url=urljoin(origin.rstrip("/") + "/", path.lstrip("/")),
        method="POST",
        timeout=timeout,
        json_body=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()


def _mcp_ping(*, origin: str, path: str, token: str) -> bool:
    try:
        body = _mcp_rpc(
            origin=origin, path=path, token=token, method="ping", timeout=10
        )
    except requests.RequestException, ValueError:
        return False
    return isinstance(body, dict) and body.get("result") == {}


def _mcp_report(*, origin: str | None, tokens: TokenFile | None) -> dict[str, object]:
    if not origin or tokens is None:
        return {}
    maintainer = tokens["maintainer"]
    organizer = {
        slug: _mcp_ping(origin=origin, path=row["path"], token=row["token"])
        for slug, row in tokens["organizer"].items()
    }
    return {
        "maintainer_ping": _mcp_ping(
            origin=origin, path=maintainer["path"], token=maintainer["token"]
        ),
        "organizer": organizer,
    }


def _advice(
    *,
    live_origin: str | None,
    tokens: TokenFile | None,
    stale_portless: bool,
    django_on_app_port: bool,
    origin: str,
    sites: list[dict[str, object]],
) -> list[str]:
    lines: list[str] = []
    if live_origin is None:
        lines.append(
            "Site.domain did not serve /healthz/. Start with `mise run start`."
        )
        if django_on_app_port:
            lines.append(
                "Django answered on :8000 with this Host. Portless is not serving "
                "Site.domain. Do not pkill portless."
            )
    if tokens is None:
        lines.append("No .local/mcp-tokens.json. Run `mise run mcp-token`.")
    if stale_portless:
        lines.append(
            "Portless on :1355 answered without /healthz/. That is a stale proxy, "
            "not the app. Do not pkill portless."
        )
    if extra := [site for site in sites if site["origin"] != origin]:
        hosts = ", ".join(str(site["origin"]) for site in extra)
        lines.append(
            "Public pages use the sphere Site, not always SITE_ID. "
            f"Also present: {hosts}. Open that origin for the matching event."
        )
    return lines


def doctor() -> dict[str, object]:
    settings = _django_settings()
    origin = _site_origin()
    parsed = urlparse(origin)
    site_health = _healthz(origin)
    django_direct = _healthz("http://127.0.0.1:8000", host=parsed.netloc)
    portless = _healthz("http://127.0.0.1:1355", host=parsed.netloc)
    live_origin = origin if site_health["ok"] else None
    tokens = load_token_file(TOKENS_PATH)
    stale_portless = (
        portless["portless"] and not portless["ok"] and portless["status"] != 0
    )
    sites = _sites()
    return {
        "ok": live_origin is not None,
        "base_url": live_origin,
        "site_origin": origin,
        "sites": sites,
        "db": str(settings.DATABASES["default"]["NAME"]),
        "tokens_path": str(TOKENS_PATH) if tokens else None,
        "organizer_events": list(tokens["organizer"]) if tokens else [],
        "mcp": _mcp_report(origin=live_origin, tokens=tokens),
        "stale_portless": stale_portless,
        "probes": [
            {key: probe[key] for key in ("url", "host", "status", "ok", "portless")}
            for probe in (site_health, django_direct, portless)
        ],
        "advice": _advice(
            live_origin=live_origin,
            tokens=tokens,
            stale_portless=stale_portless,
            django_on_app_port=django_direct["ok"],
            origin=origin,
            sites=sites,
        ),
    }


def _require_base() -> str:
    report = doctor()
    if not report["ok"] or not report["base_url"]:
        raise SystemExit("Instance is not healthy.\n" + "\n".join(report["advice"]))
    return str(report["base_url"])


def cmd_launch() -> int:
    report = doctor()
    if report["ok"] and report["base_url"]:
        print(json.dumps({"mode": "attach", **report}, indent=2))
        return 0
    print(
        "No healthy instance at Site.domain. Start one in another terminal:\n"
        "  mise run start\n"
        "Do not reuse `mise run kill` / test:e2e:kill. Those kill by port.",
        file=sys.stderr,
    )
    print(json.dumps(report, indent=2))
    return 1


def cmd_cleanup() -> int:
    print(json.dumps({"cleaned": False, "note": "this skill never starts a server"}))
    return 0


def _browser(*args: str, required: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["aubx", "agent-browser", *args],
        check=False,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )
    if required and result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _resolve_url(target: str) -> str:
    if target.startswith(HTTP_ORIGIN_PREFIXES):
        return target
    return urljoin(_require_base().rstrip("/") + "/", target.lstrip("/"))


def cmd_open(target: str) -> int:
    result = _browser("open", _resolve_url(target))
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
    _browser("eval", UNPIN_SCROLL, required=False)
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


def _organizer_row(tokens: TokenFile, *, event: str | None) -> OrganizerToken:
    if not (organizer := tokens["organizer"]):
        raise SystemExit("No organizer tokens. Run `mise run mcp-token`.")
    if event:
        if (row := organizer.get(event)) is None:
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
    if (tokens := load_token_file(TOKENS_PATH)) is None:
        raise SystemExit("No .local/mcp-tokens.json. Run `mise run mcp-token`.")
    row: MaintainerToken | OrganizerToken = (
        tokens["maintainer"]
        if scope == "maintainer"
        else _organizer_row(tokens, event=event)
    )
    try:
        parsed_args = json.loads(arguments)
    except json.JSONDecodeError as error:
        message = f"arguments must be JSON: {error}"
        raise SystemExit(message) from error
    try:
        print(
            json.dumps(
                _mcp_rpc(
                    origin=str(report["base_url"]),
                    path=row["path"],
                    token=row["token"],
                    method="tools/call",
                    params={"name": tool, "arguments": parsed_args},
                    timeout=60,
                )
            )
        )
    except requests.HTTPError as error:
        raise SystemExit(error.response.text) from error
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Drive the local ludamus app for agent verification."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="Is this instance worth driving?")
    sub.add_parser("base-url", help="Print the live origin")
    sub.add_parser("launch", help="Attach if Site.domain is healthy")
    sub.add_parser("cleanup", help="No-op: this skill never starts a server")
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
    if (handler := commands.get(args.cmd)) is None:
        message = f"unhandled command {args.cmd}"
        raise SystemExit(message)
    return handler()


if __name__ == "__main__":
    raise SystemExit(main())
