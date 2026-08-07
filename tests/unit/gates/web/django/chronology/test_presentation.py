import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from ludamus.gates.web.django.chronology.event_presentation import SessionData
from ludamus.gates.web.django.chronology.schedule import (
    build_schedule_days,
    group_sessions_by_state,
)
from ludamus.pacts import AgendaItemDTO
from ludamus.pacts.legacy import SessionFieldValueDTO


def _make_session_data(
    effective_participants_limit: int = 10, enrolled_count: int = 0, **overrides
) -> SessionData:
    defaults = {
        "agenda_item": MagicMock(),
        "is_enrollment_available": True,
        "presenter": MagicMock(),
        "session": MagicMock(),
        "is_full": enrolled_count >= effective_participants_limit,
        "full_participant_info": "",
        "effective_participants_limit": effective_participants_limit,
        "enrolled_count": enrolled_count,
        "session_participations": [],
        "loc": MagicMock(),
    }
    return SessionData(**(defaults | overrides))


class TestSessionDataSpotsLeft:
    def test_no_enrollments(self):
        data = _make_session_data(effective_participants_limit=10, enrolled_count=0)

        assert data.spots_left == data.effective_participants_limit

    def test_some_enrollments(self):
        data = _make_session_data(effective_participants_limit=10, enrolled_count=3)

        assert (
            data.spots_left == data.effective_participants_limit - data.enrolled_count
        )

    def test_full(self):
        data = _make_session_data(effective_participants_limit=10, enrolled_count=10)

        assert data.spots_left == 0

    def test_over_limit_clamps_to_zero(self):
        data = _make_session_data(effective_participants_limit=5, enrolled_count=7)

        assert data.spots_left == 0

    def test_unlimited_returns_maxsize(self):
        data = _make_session_data(effective_participants_limit=0, enrolled_count=5)

        assert data.spots_left == sys.maxsize


class TestSessionDataSpotsScarce:
    @pytest.mark.parametrize(
        ("limit", "enrolled", "expected"),
        (
            (10, 0, False),
            (10, 5, False),
            (10, 7, False),
            (10, 8, False),
            (10, 9, True),
            (10, 10, True),
            (5, 4, False),
            (5, 5, True),
            (1, 1, True),
            (1, 0, False),
        ),
    )
    def test_threshold(self, limit, enrolled, expected):
        data = _make_session_data(
            effective_participants_limit=limit, enrolled_count=enrolled
        )

        assert data.spots_scarce is expected

    def test_zero_limit_is_not_scarce(self):
        data = _make_session_data(effective_participants_limit=0, enrolled_count=0)

        assert data.spots_scarce is False


class TestSessionDataWaitingCount:
    def test_default_is_zero(self):
        data = _make_session_data()

        assert data.waiting_count == 0

    def test_explicit_value(self):
        waiting = 3
        data = _make_session_data(waiting_count=waiting)

        assert data.waiting_count == waiting


def _loc(path="", parent_slug="", parent_name="", space_name=""):
    return {
        "space_name": space_name,
        "parent_slug": parent_slug,
        "parent_name": parent_name,
        "path": path,
    }


class TestSessionDataLocationLabel:
    def test_returns_full_tree_path(self):
        data = _make_session_data(loc=_loc(path="Hotel Mariot > Sala A > Stół 1"))

        assert data.location_label == "Hotel Mariot > Sala A > Stół 1"

    def test_empty_path_returns_empty(self):
        data = _make_session_data(loc=_loc())

        assert not data.location_label


class TestSessionDataFilterCategories:
    def test_empty_without_tracks_or_category(self):
        data = _make_session_data()

        assert not data.filter_categories

    def test_track_names_become_track_pairs(self):
        data = _make_session_data(track_names=["Main", "Side"])

        assert data.filter_categories == "__track:Main;__track:Side"

    def test_category_becomes_category_pair(self):
        data = _make_session_data(category_name="RPG")

        assert data.filter_categories == "__category:RPG"

    def test_track_and_category_combined(self):
        data = _make_session_data(track_names=["Main"], category_name="RPG")

        assert data.filter_categories == "__track:Main;__category:RPG"

    def test_prepends_public_field_tags(self):
        data = _make_session_data(
            field_values=[
                SessionFieldValueDTO(
                    field_name="System",
                    field_question="",
                    field_slug="system",
                    field_type="select",
                    is_public=True,
                    value=["D&D"],
                )
            ],
            track_names=["Main"],
            category_name="RPG",
        )

        assert data.filter_categories == "system:D&D;__track:Main;__category:RPG"


class TestBuildScheduleDays:
    def test_skips_unscheduled_pending_proposal(self):
        pending = _make_session_data(agenda_item=None)
        scheduled = _make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, 10, 12, tzinfo=UTC),
                end_time=datetime(2026, 7, 10, 14, tzinfo=UTC),
                pk=1,
                session_confirmed=True,
            )
        )

        days = build_schedule_days({1: pending, 2: scheduled})

        assert len(days) == 1
        assert days[0].hours[0].sessions == [scheduled]

    def test_only_pending_proposals_yield_no_days(self):
        pending = _make_session_data(agenda_item=None)

        assert not build_schedule_days({1: pending})


class TestGroupSessionsByState:
    def test_skips_unscheduled_pending_proposal(self):
        pending = _make_session_data(agenda_item=None)

        assert group_sessions_by_state({1: pending}) == ({}, {}, {})
