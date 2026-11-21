from __future__ import annotations

import os
import subprocess
import sys

from tests.integration.repo_paths import REPO_ROOT

COLD_BOOT = """
from scripts.django_boot import boot_django
boot_django()
from django.apps import apps
assert apps.ready
"""


def test_boot_django_sets_up_apps_in_a_fresh_interpreter() -> None:
    # NOTE: pytest-django has already set Django up in this process, so only a
    # fresh interpreter reaches the path where `django.apps` is not imported yet.
    # It also exports DJANGO_SETTINGS_MODULE and mise exports PYTHONPATH, which
    # would stand in for the settings and `src` path boot_django has to supply.
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DJANGO_SETTINGS_MODULE", "PYTHONPATH"}
    }
    result = subprocess.run(
        [sys.executable, "-c", COLD_BOOT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
