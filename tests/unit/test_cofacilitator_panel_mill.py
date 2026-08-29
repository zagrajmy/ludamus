"""Unit tests for the co-facilitator extraction mill."""

import pytest

from ludamus.mills.panel_cofacilitators import (
    guess_names,
    split_people,
    suggested_values,
)
from ludamus.pacts.fields import OrganizerFieldDTO


def _field(pk: int, name: str, slug: str) -> OrganizerFieldDTO:
    return OrganizerFieldDTO(
        field_type="text",
        name=name,
        options=[],
        order=pk,
        pk=pk,
        question=name,
        slug=slug,
    )


class TestSplitPeople:
    @pytest.mark.parametrize(
        ("value", "expected"),
        (
            ("Jan Kowalski i Piotr Nowak", ["Jan Kowalski", "Piotr Nowak"]),
            ("Piotr Nowak; Błażej Gwóźdź", ["Piotr Nowak", "Błażej Gwóźdź"]),
            ("Anna Kot, Ewa Lis oraz Jan Bąk", ["Anna Kot", "Ewa Lis", "Jan Bąk"]),
            ("- Anna Kot\n- Ewa Lis", ["Anna Kot", "Ewa Lis"]),
            ("Jan Kowalski", ["Jan Kowalski"]),
            ("Jan I. Kowalski", ["Jan I. Kowalski"]),
            ("   ", []),
        ),
    )
    def test_splits_the_separators_organizers_write(self, value, expected):
        assert split_people(value) == expected


class TestGuessNames:
    @pytest.mark.parametrize(
        ("fragment", "expected"),
        (
            ('John "Wildstyle" Smith', ("John", "Smith")),
            ("Jan Kowalski", ("Jan", "Kowalski")),
            ("Jan Maria Kowalski", ("Jan", "Kowalski")),
            ("Kot", ("Kot", "")),
            ('"Wildstyle"', ("", "")),
        ),
    )
    def test_reads_the_first_and_last_name_around_a_nickname(self, fragment, expected):
        assert guess_names(fragment) == expected


class TestSuggestedValues:
    def test_fills_the_events_own_name_fields(self):
        fields = [
            _field(1, "Imię", "imie"),
            _field(2, "Nazwisko", "nazwisko"),
            _field(3, "Miasto", "miasto"),
        ]

        values = suggested_values(fragment='John "Wildstyle" Smith', fields=fields)

        assert values == {"imie": "John", "nazwisko": "Smith"}

    def test_suggests_nothing_when_the_event_has_no_name_fields(self):
        assert not suggested_values(
            fragment="Jan Kowalski", fields=[_field(1, "X", "x")]
        )
