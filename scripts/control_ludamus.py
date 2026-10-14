#!/usr/bin/env python3
"""Launch and drive a disposable ludamus instance for agent verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from urllib.parse import urljoin, urlparse

import requests

from scripts.mcp_token_file import (
    MaintainerToken,
    OrganizerToken,
    TokenFile,
    load_token_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_DIR = REPO_ROOT / ".local" / "verify-ludamus"
RUNS_DIR = VERIFY_DIR / "runs"
EVIDENCE_ROOT = VERIFY_DIR / "evidence"
CURRENT_PATH = VERIFY_DIR / "current.json"
MANIFEST_PATH = REPO_ROOT / "src" / "ludamus" / "static" / "vite" / "manifest.json"
SEED_PORT_SUFFIX = ":8000"
SEED_SCRIPTS = (
    "tests/e2e/scripts/bootstrap_data.py",
    "tests/e2e/scripts/bootstrap_facilitators.py",
    "tests/e2e/scripts/bootstrap_timetable.py",
    "tests/e2e/scripts/bootstrap_large_event.py",
)
# NOTE: past COMPACT_SCHEDULE_MIN_SESSIONS (20), so perf-marathon gets Rooms.
LARGE_EVENT_SESSIONS = "40"
READY_PATHS = ("/", "/event/autumn-open/")
READY_TIMEOUT_SECONDS = 90
STOP_TIMEOUT_SECONDS = 10
HTTP_OK = 200
HTTP_ORIGIN_PREFIXES = ("http://", "https://")
DOTENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
STYLESHEET = re.compile(r'href="([^"]+\.css)"')
ANONYMOUS = "anonymous"
UNPIN_SCROLL = (
    "const s=document.getElementById('app-scroll'); if(s){"
    "document.documentElement.style.height='auto';"
    "document.body.style.height='auto';"
    "document.body.style.overflow='visible';"
    "s.style.height='auto';s.style.overflow='visible';}"
)


class Run(TypedDict):
    run_id: str
    pid: int
    port: int
    base_url: str
    run_dir: str
    evidence_dir: str
    db: str
    fingerprint: str
    persona: str
    launched_at: str


class LaunchError(RuntimeError):
    pass


def _dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := DOTENV_LINE.match(line.strip()):
            values[match[1]] = match[2].strip().strip("'\"")
    return values


def _source_fingerprint() -> str:
    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, cwd=REPO_ROOT
        ).stdout

    digest = hashlib.sha256()
    digest.update(git("rev-parse", "HEAD"))
    digest.update(git("diff", "HEAD"))
    for name in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if (path := REPO_ROOT / name.decode()).is_file():
            digest.update(name)
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _instance_env(*, run_dir: Path, port: int) -> dict[str, str]:
    app_keys = set(_dotenv(REPO_ROOT / ".env.schema"))
    env = {key: value for key, value in os.environ.items() if key not in app_keys}
    env.update(_dotenv(REPO_ROOT / ".env.e2e"))
    relative = run_dir.relative_to(REPO_ROOT)
    env.update(
        {
            "DB_NAME": str(run_dir / "db.sqlite3"),
            "DBOS_SYSTEM_DATABASE_URL": f"sqlite:///{run_dir / 'dbos_sys.sqlite'}",
            "ROOT_DOMAIN": f"localhost:{port}",
            "E2E_BASE_URL": f"http://localhost:{port}",
            "E2E_STATE_DIR": str(run_dir / "personas"),
            "EMAIL_URL": f"filemail:///{relative / 'mail'}",
            "LARGE_EVENT_SESSIONS": LARGE_EVENT_SESSIONS,
            "PYTHONPATH": "src",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _step(*, command: list[str], env: dict[str, str], log: Path) -> None:
    with log.open("a", encoding="utf-8") as sink:
        sink.write(f"\n$ {' '.join(command)}\n")
        sink.flush()
        result = subprocess.run(
            command,
            check=False,
            cwd=REPO_ROOT,
            env=env,
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
    if result.returncode != 0:
        tail = "\n".join(log.read_text(encoding="utf-8").splitlines()[-30:])
        message = f"`{' '.join(command)}` exited {result.returncode}:\n{tail}"
        raise LaunchError(message)


def _move_seed_hosts(*, db: Path, port: int) -> None:
    with sqlite3.connect(db) as connection:
        connection.execute(
            "UPDATE django_site SET domain = substr(domain, 1, length(domain) - ?)"
            " || ? WHERE domain LIKE ?",
            (len(SEED_PORT_SUFFIX), f":{port}", f"%{SEED_PORT_SUFFIX}"),
        )


def _get(url: str) -> requests.Response | None:
    if urlparse(url).scheme not in {"http", "https"}:
        message = f"Refusing non-http URL {url!r}"
        raise ValueError(message)
    try:
        return requests.get(url, timeout=10)
    except requests.RequestException:
        return None


def _usable(base_url: str) -> list[str]:
    problems: list[str] = []
    health = _get(f"{base_url}/healthz/")
    if health is None or '"status": "ok"' not in health.text:
        return ["/healthz/ is not ok"]
    home = _get(f"{base_url}/")
    for path in READY_PATHS:
        response = home if path == "/" else _get(f"{base_url}{path}")
        if response is None or response.status_code != HTTP_OK:
            status = "no answer" if response is None else response.status_code
            problems.append(f"{path} -> {status}")
    if home is not None and (sheet := STYLESHEET.search(home.text)):
        css = _get(urljoin(f"{base_url}/", sheet[1]))
        if css is None or css.status_code != HTTP_OK:
            problems.append(f"stylesheet {sheet[1]} is not served")
    elif home is not None:
        problems.append("/ links no stylesheet; the client build is missing")
    return problems


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_ready(*, pid: int, base_url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    problems = ["not polled yet"]
    while time.monotonic() < deadline:
        if os.waitpid(pid, os.WNOHANG) != (0, 0):
            message = "runserver exited before it was ready; see server.log"
            raise LaunchError(message)
        if not (problems := _usable(base_url)):
            return
        time.sleep(1)
    message = f"not usable after {READY_TIMEOUT_SECONDS}s: {'; '.join(problems)}"
    raise LaunchError(message)


def _stop(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
    while time.monotonic() < deadline and _alive(pid):
        time.sleep(0.2)
    if _alive(pid):
        os.killpg(pid, signal.SIGKILL)


def _load_run() -> Run | None:
    if not CURRENT_PATH.exists():
        return None
    run: Run = json.loads(CURRENT_PATH.read_text(encoding="utf-8"))
    return run


def _save_run(run: Run) -> None:
    CURRENT_PATH.write_text(json.dumps(run, indent=2), encoding="utf-8")


def _require_run() -> Run:
    if (run := _load_run()) is None:
        raise SystemExit("No verification instance. Run `control-ludamus launch`.")
    return run


def _seed(*, run_dir: Path, port: int, log: Path) -> None:
    env = _instance_env(run_dir=run_dir, port=port)
    python = sys.executable
    (run_dir / "personas").mkdir()
    for command in (
        [python, "-m", "django", "migrate", "--noinput"],
        [python, "-m", "django", "createcachetable"],
        [python, "-m", "django", "downloadvendor"],
        *([python, script] for script in SEED_SCRIPTS),
    ):
        _step(command=command, env=env, log=log)
    _move_seed_hosts(db=run_dir / "db.sqlite3", port=port)
    _step(
        command=[
            python,
            "-m",
            "scripts.mint_mcp_tokens",
            "--output",
            str(run_dir / "mcp-tokens.json"),
        ],
        env=env,
        log=log,
    )
    _step(command=["aubr", "-C", "src/ludamus/client", "build"], env=env, log=log)


def _start_server(*, run_dir: Path, port: int) -> int:
    argv = [
        sys.executable,
        "-m",
        "django",
        "runserver",
        "--insecure",
        "--noreload",
        f"localhost:{port}",
    ]
    log = str(run_dir / "server.log")
    return os.posix_spawn(
        sys.executable,
        argv,
        _instance_env(run_dir=run_dir, port=port),
        file_actions=[
            (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
            (os.POSIX_SPAWN_OPEN, 1, log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644),
            (os.POSIX_SPAWN_DUP2, 1, 2),
        ],
        setpgroup=0,
    )


def _keep_logs(run: Run) -> None:
    evidence = Path(run["evidence_dir"])
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ("launch.log", "server.log"):
        if (source := Path(run["run_dir"]) / name).exists():
            shutil.copy2(source, evidence / name)


def _teardown(run: Run) -> None:
    if run["pid"] > 0:
        _stop(run["pid"])
    _browser(run, "close", required=False)
    _keep_logs(run)
    shutil.rmtree(run["run_dir"], ignore_errors=True)
    CURRENT_PATH.unlink()


def cmd_launch() -> int:
    if (existing := _load_run()) is not None:
        if existing["pid"] > 0 and _alive(existing["pid"]):
            print(json.dumps({"mode": "already-running", **existing}, indent=2))
            return 0
        _teardown(existing)
    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    port = _free_port()
    run: Run = {
        "run_id": run_id,
        "pid": 0,
        "port": port,
        "base_url": f"http://localhost:{port}",
        "run_dir": str(run_dir),
        "evidence_dir": str(EVIDENCE_ROOT / run_id),
        "db": str(run_dir / "db.sqlite3"),
        "fingerprint": _source_fingerprint(),
        "persona": ANONYMOUS,
        "launched_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    _save_run(run)
    try:
        _seed(run_dir=run_dir, port=port, log=run_dir / "launch.log")
        run["pid"] = _start_server(run_dir=run_dir, port=port)
        _save_run(run)
        _wait_ready(pid=run["pid"], base_url=run["base_url"])
    except LaunchError as error:
        print(f"Launch failed: {error}", file=sys.stderr)
        print("Logs are kept; run `control-ludamus cleanup`.", file=sys.stderr)
        return 1
    print(json.dumps({"mode": "launched", **run}, indent=2))
    return 0


def _listener_pids(port: int) -> list[int] | None:
    if shutil.which("lsof") is None:
        return None
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(pid) for pid in result.stdout.split()]


def _sites(db: Path) -> list[str]:
    if not db.exists():
        return []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT domain FROM django_site ORDER BY id")
        return [f"http://{domain}" for (domain,) in rows]


def _personas(run: Run) -> list[str]:
    folder = Path(run["run_dir"]) / "personas"
    names = sorted(
        path.name.removeprefix(".auth-state").removeprefix("-").removesuffix(".json")
        or "e2e-tester"
        for path in folder.glob(".auth-state*.json")
    )
    return [ANONYMOUS, *names]


def doctor() -> dict[str, object]:
    if (run := _load_run()) is None:
        return {"ok": False, "advice": ["No instance. Run `control-ludamus launch`."]}
    alive = run["pid"] > 0 and _alive(run["pid"])
    listeners = _listener_pids(run["port"])
    owns_port = listeners is None or any(
        _alive(pid) and os.getpgid(pid) == run["pid"] for pid in listeners
    )
    problems = _usable(run["base_url"]) if alive else ["runserver is not running"]
    fresh = _source_fingerprint() == run["fingerprint"]
    advice = [*problems]
    if not owns_port:
        advice.append(f"Port {run['port']} belongs to another process. Relaunch.")
    if not fresh:
        advice.append("Source changed since launch. Run cleanup, then launch.")
    return {
        "ok": alive and owns_port and not problems,
        "fresh": fresh,
        "base_url": run["base_url"],
        "run_id": run["run_id"],
        "pid": run["pid"],
        "port_owner_checked": listeners is not None,
        "db": run["db"],
        "evidence_dir": run["evidence_dir"],
        "persona": run["persona"],
        "personas": _personas(run),
        "sites": _sites(Path(run["db"])),
        "advice": advice,
    }


def cmd_doctor() -> int:
    report = doctor()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def _require_healthy() -> Run:
    report = doctor()
    if not report["ok"]:
        advice = report["advice"]
        lines = advice if isinstance(advice, list) else []
        raise SystemExit(
            "Instance is not healthy.\n" + "\n".join(str(line) for line in lines)
        )
    return _require_run()


def _session(run: Run) -> str:
    return f"verify-ludamus-{run['run_id']}"


def _browser(
    run: Run, *args: str, required: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["aubx", "agent-browser", "--session", _session(run), *args],
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


def _persona_path(run: Run, name: str) -> str:
    suffix = "" if name == "e2e-tester" else f"-{name}"
    return str(Path(run["run_dir"]) / "personas" / f".auth-state{suffix}.json")


def _echo(result: subprocess.CompletedProcess[str]) -> int:
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return 0


def _resolve_url(run: Run, target: str) -> str:
    if target.startswith(HTTP_ORIGIN_PREFIXES):
        return target
    return urljoin(run["base_url"] + "/", target.lstrip("/"))


def _evidence_path(run: Run, path: str) -> Path:
    dest = Path(path)
    if not dest.is_absolute():
        dest = Path(run["evidence_dir"]) / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    return dest


def cmd_persona(name: str) -> int:
    run = _require_run()
    if name not in _personas(run):
        known = ", ".join(_personas(run))
        message = f"No persona {name!r}. Have: {known}"
        raise SystemExit(message)
    _browser(run, "close", required=False)
    if name != ANONYMOUS:
        state = json.loads(Path(_persona_path(run, name)).read_text(encoding="utf-8"))
        for cookie in state["cookies"]:
            _browser(
                run,
                "cookies",
                "set",
                cookie["name"],
                cookie["value"],
                "--domain",
                cookie["domain"],
                "--path",
                cookie["path"],
                *(["--httpOnly"] if cookie["httpOnly"] else []),
            )
    run["persona"] = name
    _save_run(run)
    print(json.dumps({"persona": name, "session": _session(run)}))
    return 0


def cmd_open(target: str) -> int:
    run = _require_healthy()
    return _echo(_browser(run, "open", _resolve_url(run, target)))


def cmd_snapshot(path: str) -> int:
    run = _require_run()
    dest = _evidence_path(run, path)
    result = _browser(run, "snapshot")
    dest.write_text(result.stdout, encoding="utf-8")
    print(result.stdout, end="")
    print(json.dumps({"path": str(dest)}))
    return 0


def cmd_screenshot(path: str) -> int:
    run = _require_run()
    dest = _evidence_path(run, path)
    _browser(run, "eval", UNPIN_SCROLL, required=False)
    print(_browser(run, "screenshot", "--full", str(dest)).stdout, end="")
    print(json.dumps({"path": str(dest)}))
    return 0


def cmd_find(*, locator: str, value: str, action: str, name: str | None) -> int:
    args = ["find", locator, value, action]
    if name:
        args.extend(["--name", name])
    return _echo(_browser(_require_run(), *args))


def cmd_press(*, role: str, name: str, key: str) -> int:
    run = _require_run()
    needle = f'{role} "{name}" [ref='
    for line in _browser(run, "snapshot").stdout.splitlines():
        if needle in line:
            ref = line.split(needle, 1)[1].split("]", 1)[0].split(",", 1)[0]
            _browser(run, "focus", f"@{ref}")
            return _echo(_browser(run, "press", key))
    message = f"No {role} named {name!r} in the current snapshot."
    raise SystemExit(message)


def cmd_browser(args: list[str]) -> int:
    forwarded = args[1:] if args[:1] == ["--"] else args
    return _echo(_browser(_require_run(), *forwarded))


def _organizer_row(tokens: TokenFile, *, event: str | None) -> OrganizerToken:
    if not (organizer := tokens["organizer"]):
        raise SystemExit("The run minted no organizer tokens.")
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
    run = _require_healthy()
    tokens_path = Path(run["run_dir"]) / "mcp-tokens.json"
    if (tokens := load_token_file(tokens_path)) is None:
        message = f"No {tokens_path}. Relaunch."
        raise SystemExit(message)
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
    response = requests.post(
        urljoin(run["base_url"] + "/", row["path"].lstrip("/")),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": parsed_args},
        },
        headers={"Authorization": f"Bearer {row['token']}"},
        timeout=60,
    )
    if response.status_code != HTTP_OK:
        raise SystemExit(response.text)
    print(json.dumps(response.json()))
    return 0


def cmd_cleanup() -> int:
    if (run := _load_run()) is None:
        print(json.dumps({"cleaned": False, "note": "no instance to clean up"}))
        return 0
    _teardown(run)
    print(
        json.dumps(
            {"cleaned": True, "run_id": run["run_id"], "evidence": run["evidence_dir"]}
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("launch", help="Seed and start a disposable instance")
    sub.add_parser("doctor", help="Is the launched instance worth driving?")
    sub.add_parser("cleanup", help="Stop the instance; evidence stays")
    persona = sub.add_parser("persona", help="Switch the signed-in user")
    persona.add_argument("name")
    open_cmd = sub.add_parser("open", help="Open a path or URL in agent-browser")
    open_cmd.add_argument("target")
    snap = sub.add_parser("snapshot", help="Accessibility snapshot into evidence")
    snap.add_argument("path")
    shot = sub.add_parser("screenshot", help="Full-page screenshot into evidence")
    shot.add_argument("path")
    browser = sub.add_parser("browser", help="Pass args through to agent-browser")
    browser.add_argument("args", nargs=argparse.REMAINDER)
    find_cmd = sub.add_parser("find", help="Find by ARIA role/name and act")
    find_cmd.add_argument("locator")
    find_cmd.add_argument("value")
    find_cmd.add_argument("action", nargs="?", default="click")
    find_cmd.add_argument("--name", default=None)
    press = sub.add_parser("press", help="Focus by ARIA role/name, press a key")
    press.add_argument("role")
    press.add_argument("name")
    press.add_argument("key")
    mcp_cmd = sub.add_parser("mcp", help="Call an MCP tool (inspect, not UI proof)")
    mcp_cmd.add_argument(
        "--scope", choices=("maintainer", "organizer"), default="organizer"
    )
    mcp_cmd.add_argument("--event", default=None)
    mcp_cmd.add_argument("tool")
    mcp_cmd.add_argument("arguments", nargs="?", default="{}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.chdir(REPO_ROOT)
    commands = {
        "launch": cmd_launch,
        "doctor": cmd_doctor,
        "cleanup": cmd_cleanup,
        "persona": lambda: cmd_persona(args.name),
        "open": lambda: cmd_open(args.target),
        "snapshot": lambda: cmd_snapshot(args.path),
        "screenshot": lambda: cmd_screenshot(args.path),
        "press": lambda: cmd_press(role=args.role, name=args.name, key=args.key),
        "browser": lambda: cmd_browser(list(args.args)),
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
