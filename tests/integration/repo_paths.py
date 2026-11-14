"""Roots the repo-wide guards walk, resolved once.

A guard handed the wrong root rglobs nothing and passes, so the root is asserted
here rather than left to fail silently in every test that walks it.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "src" / "ludamus"
TEMPLATE_ROOT = PACKAGE_ROOT / "templates"
CLIENT_SRC = PACKAGE_ROOT / "client" / "src"

assert TEMPLATE_ROOT.is_dir(), (
    f"repository root resolved to {REPO_ROOT}, which holds no "
    f"src/ludamus/templates: every guard below would scan nothing and pass"
)
