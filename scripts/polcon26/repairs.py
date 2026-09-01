"""Verified per-workbook repairs for the POLCON 2026 programme sheets.

Everything here names a concrete cell, row, or label in the current workbook.
Check the workbook before adding an entry; never infer a repair from a
similar title (see docs/agents/polcon26-programme-sync.md).
"""

from __future__ import annotations

ROOM_NAME_REPAIRS = (
    ("prelecyjny", "prelekcyjny"),
    ("prelekcyjny (aula 8 w A16)y", "prelekcyjny (aula 8 w A16)"),
    ("warsztatowaa", "warsztatowa"),
    ("Naukowy (aula w Bibliotece UZ)", "Naukowy (Biblioteka UZ)"),
    ("naukowy (aula w Bibliotece UZ)", "Naukowy (Biblioteka UZ)"),
    ("Turniejowa Games Room (sala 9 w A–20)", "Turniejowa Games Room"),
    ("Turniejowa Games Room (sala 9 w A–20", "Turniejowa Games Room"),
    ("RPG – Sesje (sala 122 w A–20)", "RPG – Sesje 4h (sala 122 w A–20)"),
)
UNLABELLED_ROOM_GROUPS: dict[str, tuple[tuple[int, int, str], ...]] = {}
TRANSPOSED_TITLE_CELLS: frozenset[tuple[str, str]] = frozenset()

FIXTURE_LANE_NAMES = {
    "Palmiarnia w A-16": (
        "Warsztaty malowania figurek",
        "Wystawa makiety",
        "Stoisko Oblivion Forge",
        "Pokazy gier bitewnych",
    ),
    "Warsztatowa Eger, Aula G": ("Nitka 1", "Nitka 2", "Nitka 3"),
}

NESTED_ROOM_LANES = {
    "Warsztatowa Eger (aula G) Nitka 1": ("Warsztatowa Eger, Aula G", 1),
    "Warsztatowa Eger (aula G) Nitka 2": ("Warsztatowa Eger, Aula G", 2),
    "Warsztatowa Eger (aula G) Nitka 3": ("Warsztatowa Eger, Aula G", 3),
}

VENUE_NAME_ALIASES = {"Gry Bitewne (Palmiarnia w A–16)": "Palmiarnia w A-16"}

SPLIT_NAME_REPAIRS = {
    ("Fundacja Dawne Komputery", "Gry"): "Fundacja Dawne Komputery i Gry"
}
