#!/usr/bin/env python3
"""Seed realistic worst-case data next to the e2e demo data.

The demo events were written against kind data: names that fit on one line,
every optional field filled, counts that never need a separator. These events
undo that, one field at a time, with values real people produce and every
string within the 255-character limit the models and forms share:

  - ``worst-case``: long hyphenated, one-letter, CJK, RTL and emoji-first
    names; a name field holding an email; markup in a title; a session for
    exactly 1 seat next to one for 1,284; a dozen tags on one card; a room
    with no capacity; a session with five facilitators.
  - ``worst-case-one``: one session, one seat, one facilitator — every count
    at exactly 1.
  - ``worst-case-empty``: published, with nothing in it.

It also seeds Aleksandra, a user whose account carries the same shape of data
(long name, unbreakable email, avatar URL that 404s, 1,284 unread
notifications), and writes her session to ``tests/e2e/.auth-state-worst.json``.

The data lives in ``worst_case_seed.py``, imported once Django is set up.
Run after ``bootstrap_data.py`` (it reuses the sphere that script creates).
Part of ``mise run test:e2e:prep``; ``tests/worst-case.spec.ts`` reads it.

Usage:
    mise run test:e2e:boot tests/e2e/scripts/bootstrap_worst_case.py
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import django

SRC_DIR = Path(__file__).resolve().parents[3] / "src"


def main() -> None:
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))
    django.setup()
    import_module("worst_case_seed").seed()


if __name__ == "__main__":
    main()
