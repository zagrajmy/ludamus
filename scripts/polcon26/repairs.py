"""Verified per-workbook repairs for the POLCON 2026 programme sheets.

Everything here names a concrete cell, row, or label in the current workbook.
Check the workbook before adding an entry; never infer a repair from a
similar title (see docs/agents/polcon26-programme-sync.md).
"""

from __future__ import annotations

from dataclasses import dataclass

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

EXCLUDED_TITLE_CELLS = {"Sobota": frozenset({"BA7", "BI7", "BA55", "BE55", "AY82"})}


@dataclass(frozen=True)
class FloatingBlock:
    room: str
    header_row: int
    title_row: int
    presenter_row: int
    description_row: int


@dataclass(frozen=True)
class NightLane:
    room_row: int
    title_row: int
    presenter_row: int | None = None
    description_row: int | None = None


@dataclass(frozen=True)
class RepairItemSpec:
    at: str
    room_row: int
    title: str
    presenters: tuple[str, ...]
    start_minutes: int
    duration_minutes: int
    description_cell: str | None = None

    @property
    def sheet(self) -> str:
        return self.at.partition("!")[0]

    @property
    def cell(self) -> str:
        return self.at.partition("!")[2]


FLOATING_BLOCKS = {
    "Sobota": (
        FloatingBlock(
            room="Namiot Konwentowy",
            header_row=1,
            title_row=2,
            presenter_row=3,
            description_row=7,
        ),
    )
}

SHIFTED_NIGHT_LANES = {
    "Sobota": (
        NightLane(room_row=4, title_row=6),
        NightLane(room_row=7, title_row=8, presenter_row=9),
    )
}

REPAIR_ITEMS = (
    RepairItemSpec(
        at="Sobota!BA55",
        room_row=55,
        title="Konkurs: rozpoznawanie anime po mundurkach",
        presenters=(),
        description_cell="BA55",
        start_minutes=22 * 60 + 30,
        duration_minutes=60,
    ),
    RepairItemSpec(
        at="Sobota!BE56",
        room_row=55,
        title="Czucie walki",
        presenters=("Michał Gmur",),
        start_minutes=23 * 60 + 30,
        duration_minutes=60,
    ),
    RepairItemSpec(
        at="Sobota!BE55",
        room_row=55,
        title="Pośpiewajmy – lub powyjmy – nasze ulubione utwory",
        presenters=(),
        description_cell="BE55",
        start_minutes=24 * 60 + 30,
        duration_minutes=60,
    ),
    RepairItemSpec(
        at="Sobota!AY82",
        room_row=82,
        title="Sesja RPG",
        presenters=("Sławek Szymański",),
        start_minutes=22 * 60,
        duration_minutes=210,
    ),
)

FIXTURE_LANE_NAMES = {
    "Palmiarnia w A-16": (
        "Warsztaty malowania figurek",
        "Wystawa makiety",
        "Stoisko Oblivion Forge",
        "Pokazy gier bitewnych",
    )
}

VENUE_NAME_ALIASES = {"Gry Bitewne (Palmiarnia w A–16)": "Palmiarnia w A-16"}

SPLIT_NAME_REPAIRS = {
    ("Fundacja Dawne Komputery", "Gry"): "Fundacja Dawne Komputery i Gry"
}
