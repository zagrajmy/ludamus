from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_boot_django_from_cold_subprocess() -> None:
    src = REPO_ROOT / "src"
    code = f"""
import sys
sys.path.insert(0, {str(src)!r})
sys.path.insert(0, {str(REPO_ROOT)!r})
from scripts.django_boot import boot_django
boot_django()
from django.apps import apps
assert apps.ready
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
