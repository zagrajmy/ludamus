"""Boot Django in a standalone script without importing it at module load."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def boot_django() -> None:
    if (src := str(REPO_ROOT / "src")) not in sys.path:
        sys.path.insert(0, src)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ludamus.edges.settings")
    django = import_module("django")
    if not django.apps.apps.ready:
        django.setup()
