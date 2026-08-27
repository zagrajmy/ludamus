"""The committed catalog must not carry a bad regeneration.

`mise run messages` extracts with `--add-location=file` and strips the
POT-Creation-Date, because that stamp guarantees a merge conflict between any
two branches that both touched the catalog. A raw `makemessages` does neither,
and one run from the wrong directory rewrites every location with the path it
happened to walk — which lands a five-thousand-line diff nobody asked for.

`messages-check` calls `makemessages` before the step that would catch this, so
a failed run still leaves the damage behind.
"""

from __future__ import annotations

from pathlib import Path

CATALOG = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ludamus"
    / "locale"
    / "pl"
    / "LC_MESSAGES"
    / "django.po"
)


def test_locations_are_repository_relative() -> None:
    stray = [
        line
        for line in CATALOG.read_text(encoding="utf-8").splitlines()
        if line.startswith("#:") and not line.startswith("#: src/")
    ]
    assert not stray, (
        "The catalog was extracted from somewhere other than the repository "
        "root — a worktree, most likely. Re-run `mise run messages`:\n"
        + "\n".join(stray[:5])
    )


def test_the_extraction_timestamp_is_stripped() -> None:
    assert '"POT-Creation-Date:' not in CATALOG.read_text(encoding="utf-8"), (
        "POT-Creation-Date is back. `mise run messages` removes it on purpose; "
        "a raw makemessages does not."
    )
