#!/usr/bin/env python3
"""Wrap `npx impeccable detect` with project-specific ignore rules.

With no args, scans tracked HTML/CSS/JS files. Positional args override.
Exits 1 if any finding remains after filtering.

Under `GITHUB_ACTIONS=true`, also emits GitHub Actions workflow commands
(`::error file=...,line=...,title=...::message`) so findings surface inline
on the PR "Files changed" tab.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# v3 is merged to pbakaus/impeccable main but not yet on npm (latest is 2.1.7).
# Pinned to main HEAD; bump to `impeccable@3.x.x` once published.
IMPECCABLE_SPEC = "github:pbakaus/impeccable#346ce25952a6d4150433e8fb1369cb59571ebc30"

IGNORE_PATH_SUBSTRINGS: tuple[str, ...] = (
    "e2e/playwright-report/",
    "tailwind.min.js",
)
# tiny-text: design opinion we don't share.
# single-font: the project deliberately uses one brand font (Outfit)
# everywhere; this whole-project heuristic flags that by design and isn't
# actionable (there's no second font to add). Its firing is also content-volume
# sensitive, so it surfaces inconsistently on unrelated CSS edits.
IGNORE_ANTIPATTERNS: frozenset[str] = frozenset({"tiny-text", "single-font"})

SCAN_GLOBS: tuple[str, ...] = ("*.html", "*.css", "*.js", "*.jsx", "*.tsx")

SNIPPET_MAX = 120


def tracked_ui_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--", *SCAN_GLOBS],
        check=True,
        capture_output=True,
        text=True,
    )
    files = [line for line in result.stdout.splitlines() if line]
    return [f for f in files if not _path_ignored(f)]


def _path_ignored(path: str) -> bool:
    return any(sub in path for sub in IGNORE_PATH_SUBSTRINGS)


def _extract_json_array(text: str) -> str | None:
    # Strip npm warnings etc. that may prefix the JSON payload.
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    return text[start : end + 1]


def run_detect(paths: list[str]) -> list[dict]:
    cmd = ["npx", "--yes", IMPECCABLE_SPEC, "detect", "--json", *paths]
    # impeccable is SHA-pinned (that is its supply-chain anchor), but a global
    # ~/.npmrc min-release-age gate also derives a `before` date that npm fails
    # to apply to the github tarball source ("Invalid time value"), silently
    # aborting the install. Point npx at an empty user-config so the gate is
    # skipped for impeccable only; the global ~/.npmrc still gates everything
    # else.
    env = {**os.environ, "NPM_CONFIG_USERCONFIG": os.devnull}
    result = subprocess.run(
        cmd, check=False, capture_output=True, text=True, env=env
    )
    # impeccable emits JSON on stdout when empty and on stderr when findings exist.
    # Sources may prefix the payload with npm warnings (e.g. git-sourced installs).
    for stream in (result.stdout, result.stderr):
        payload = _extract_json_array(stream or "")
        if payload is None:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        return data if isinstance(data, list) else []
    sys.stderr.write(f"impeccable failed (exit {result.returncode}):\n")
    sys.stderr.write(result.stdout)
    sys.stderr.write(result.stderr)
    sys.exit(result.returncode or 1)


def filter_findings(findings: list[dict]) -> list[dict]:
    return [
        f
        for f in findings
        if not _path_ignored(f.get("file", ""))
        and f.get("antipattern") not in IGNORE_ANTIPATTERNS
    ]


def _relative_path(file_path: str, repo_root: Path) -> str:
    try:
        return str(Path(file_path).resolve().relative_to(repo_root))
    except (ValueError, OSError):
        return file_path


def format_finding(finding: dict, repo_root: Path) -> str:
    file_path = _relative_path(finding.get("file", ""), repo_root)
    line = finding.get("line", "")
    antipattern = finding.get("antipattern", "?")
    name = finding.get("name", "")
    snippet = " ".join((finding.get("snippet") or "").split())
    if len(snippet) > SNIPPET_MAX:
        snippet = snippet[: SNIPPET_MAX - 3] + "..."
    head = f"{file_path}:{line} [{antipattern}] {name}"
    return f"{head}\n  {snippet}" if snippet else head


def _escape_message(text: str) -> str:
    # https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions#example-setting-an-error-message
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(text: str) -> str:
    return _escape_message(text).replace(":", "%3A").replace(",", "%2C")


def format_workflow_command(finding: dict, repo_root: Path) -> str:
    file_path = _relative_path(finding.get("file", ""), repo_root)
    raw_line = finding.get("line")
    line = raw_line if isinstance(raw_line, int) and raw_line > 0 else 1
    antipattern = finding.get("antipattern", "impeccable")
    name = finding.get("name") or antipattern
    snippet = " ".join((finding.get("snippet") or "").split())
    message = f"{name}: {snippet}" if snippet else name
    params = (
        f"file={_escape_property(file_path)},"
        f"line={line},"
        f"title={_escape_property(f'impeccable/{antipattern}')}"
    )
    return f"::error {params}::{_escape_message(message)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Paths to scan (default: tracked HTML/CSS/JS files).",
    )
    args = parser.parse_args()

    repo_root = Path.cwd().resolve()
    paths = args.paths or tracked_ui_files()
    if not paths:
        print("impeccable: no files to scan", file=sys.stderr)
        return 0

    filtered = filter_findings(run_detect(paths))
    in_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"

    for finding in filtered:
        print(format_finding(finding, repo_root))
        if in_github_actions:
            print(format_workflow_command(finding, repo_root))

    if filtered:
        print(f"\nimpeccable: {len(filtered)} issue(s)", file=sys.stderr)
        return 1
    print("impeccable: no issues", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
