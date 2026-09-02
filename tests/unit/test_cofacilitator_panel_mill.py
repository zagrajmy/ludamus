"""Unit tests for the co-facilitator extraction mill."""

from unittest.mock import Mock

import pytest

from ludamus.mills.panel_cofacilitators import (
    CofacilitatorPanelService,
    guess_names,
    is_resolved,
    resolved_keys,
    split_people,
    suggested_values,
)
from ludamus.pacts.fields import OrganizerFieldDTO
from ludamus.pacts.legacy import NotFoundError


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


class TestIsResolved:
    @pytest.mark.parametrize(
        ("fragment", "expected"),
        (
            ("Jan Kowalski", True),
            ("jan  kowalski", True),
            ("Piotr Nowak", True),
            ("Ewa Lis", False),
        ),
    )
    def test_counts_a_name_decided_by_hand_or_already_on_the_session(
        self, fragment, expected
    ):
        keys = resolved_keys(
            decided=["piotr nowak"], facilitator_names=["Jan Kowalski"]
        )

        assert is_resolved(fragment=fragment, resolved=keys) is expected

    def test_leaves_every_name_open_when_nothing_was_decided(self):
        keys = resolved_keys(decided=[], facilitator_names=[])

        assert not is_resolved(fragment="Jan Kowalski", resolved=keys)


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


class TestResolveField:
    def test_refuses_a_pick_that_is_not_one_of_this_events_field_ids(self):
        repos = Mock()
        service = CofacilitatorPanelService(
            transaction=Mock(), repos=repos, facilitator_panel=Mock()
        )

        with pytest.raises(NotFoundError):
            service.resolve_field(event_id=1, raw="co-facilitators")

        assert not repos.mock_calls
