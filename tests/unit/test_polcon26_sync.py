import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "sync_polcon26_programme",
    Path(__file__).resolve().parents[2] / "scripts" / "sync_polcon26_programme.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
sync = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = sync
_SPEC.loader.exec_module(sync)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("RPG - sesje 4h [sala 108]", "RPG — sala 108"),
        ("RPG - prelekcyjny", "RPG prelekcje — sala 115"),
        ("RPG - prelekcyjny sala 117", "RPG prelekcje — sala 117"),
        ("Sala 20 - warsztaty", "Sala 20 — warsztatowa"),
        ("Sala 12 - Retro gralnia A16", "Sala 12 — Retro Gralnia"),
        ("Manga i anime sala 106", "Manga i anime — sala 106"),
        ("[naukowy]", "Naukowy (Biblioteka UZ)"),
        ("Turniejowa Games room", "Turniejowa Games Room"),
        ("prelecyjny (aula 8 w A16)y", "Prelekcyjny (aula 8 w A16)"),
        ("  sala\n 5  ", "Sala 5"),
    ),
)
def test_canonical_room(raw: str, expected: str) -> None:
    assert sync.canonical_room(raw) == expected


@pytest.mark.parametrize(
    ("room", "expected"),
    (
        ("RPG — sala 108", "RPG"),
        ("Manga i anime — sala 106", "Manga i anime"),
        ("Sala 12 — Retro Gralnia", "Retro Gralnia"),
        ("Turniejowa Games Room", "Games Room"),
        ("Naukowy (Biblioteka UZ)", "Nauka"),
        ("Aula A", "Prelekcje"),
    ),
)
def test_track_for(room: str, expected: str) -> None:
    assert sync.track_for(room) == expected


@pytest.mark.parametrize(
    ("room", "title", "expected"),
    (
        ("RPG — sala 108", "Kryta Forteca", "Sesja RPG"),
        ("RPG prelekcje — sala 115", "Jak prowadzić", "Prelekcja"),
        ("Sala 20 — warsztatowa", "Kuźnia", "Warsztaty"),
        ("Aula A", "Stwórz własną mapę", "Warsztaty"),
        ("Aula A", "Wielki quiz fantastyki", "Konkurs"),
        ("Games Room", "Gry planszowe", "Strefa stała"),
        ("Aula A", "Panel o wydawnictwach", "Panel dyskusyjny"),
        ("Aula A", "Historia fandomu", "Prelekcja"),
    ),
)
def test_category_for(room: str, title: str, expected: str) -> None:
    assert sync.category_for(room, title) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("  Wielka   prelekcja ", "Wielka prelekcja"),
        ("Tytuł", None),
        ("???? tytuł", None),
        ("Zaproponowałem na razie coś", None),
        ("", None),
        (None, None),
        (42, None),
    ),
)
def test_clean_title(value: object, expected: str | None) -> None:
    assert sync.clean_title(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("  Prawdziwy opis  ", "Prawdziwy opis"),
        ("Potrzebny opis!", ""),
        ("Dodać opis do tego", ""),
        ("opis", ""),
        (None, ""),
    ),
)
def test_clean_description(value: object, expected: str) -> None:
    assert sync.clean_description(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("Prowadzący: Anna Kowalska", ["Anna Kowalska"]),
        ("Anna Kowalska, Jan Nowak", ["Anna Kowalska", "Jan Nowak"]),
        ("Anna Kowalska i Jan Nowak", ["Anna Kowalska", "Jan Nowak"]),
        ("Prowadzenie: Anna; Jan", ["Anna", "Jan"]),
        ("????", []),
        ("nikt", []),
        ("W zależności od ilości chętnych", []),
        (None, []),
    ),
)
def test_presenter_names(value: object, expected: list[str]) -> None:
    assert sync.presenter_names(value) == expected


@pytest.mark.parametrize(
    ("physical_room", "lane_index", "expected"),
    (
        ("RPG — sala 108", 2, ("RPG — sala 108 — stół 2", "Stół 2")),
        ("Games Room", 3, ("Games Room — stanowisko 3", "Stanowisko 3")),
    ),
)
def test_lane_names(
    physical_room: str, lane_index: int, expected: tuple[str, str]
) -> None:
    assert sync.lane_names(physical_room, lane_index) == expected


@pytest.mark.parametrize(
    ("reference", "expected"), (("A1", 0), ("B3", 1), ("Z9", 25), ("AA1", 26))
)
def test_column_index(reference: str, expected: int) -> None:
    assert sync.column_index(reference) == expected


@pytest.mark.parametrize("index", (0, 1, 25, 26, 51, 701))
def test_column_name_roundtrips(index: int) -> None:
    assert sync.column_index(f"{sync.column_name(index)}1") == index


@pytest.mark.parametrize(
    ("duration", "expected"),
    (
        (timedelta(minutes=45), "PT45M"),
        (timedelta(hours=1), "PT1H"),
        (timedelta(hours=1, minutes=30), "PT1H30M"),
    ),
)
def test_iso_duration(duration: timedelta, expected: str) -> None:
    assert sync.iso_duration(duration) == expected


def test_failure_detail_summarizes_batch_failures() -> None:
    response_text = (
        '{"summary": {"total": 2, "succeeded": 1, "failed": 1}, "results": '
        '[{"index": 0, "status": "ok"}, {"index": 1, "status": "failed", '
        '"error": "Resource not found"}]}'
    )

    detail = sync.failure_detail(response_text)

    assert "failed" in detail
    assert "Resource not found" in detail


def test_failure_detail_passes_through_plain_text() -> None:
    assert sync.failure_detail("boom") == "boom"
