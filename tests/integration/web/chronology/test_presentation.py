from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from ludamus.gates.web.django.chronology.event_presentation import (
    CloudPill,
    SessionData,
    field_pills,
    filterable_flag_fields,
)
from ludamus.gates.web.django.chronology.schedule import (
    build_card_days,
    build_schedule_days,
    group_sessions_by_state,
)
from ludamus.pacts import AgendaItemDTO
from ludamus.pacts.fields import OrganizerFieldDTO, SessionFieldType
from ludamus.pacts.legacy import SessionFieldValueDTO
from tests.integration.web.chronology.helpers import make_session_data


def _answer(
    slug: str, field_type: SessionFieldType, *, value: object, is_public: bool = True
) -> SessionFieldValueDTO:
    return SessionFieldValueDTO(
        field_icon=f"{slug}-icon",
        field_name=slug.title(),
        field_question="",
        field_slug=slug,
        field_type=field_type,
        is_public=is_public,
        value=value,
    )


class TestSessionDataSpotsLeft:
    def test_over_limit_clamps_to_zero(self):
        data = make_session_data(effective_participants_limit=5, enrolled_count=7)

        assert data.spots_left == 0


class TestSessionDataTakesEnrollment:
    def test_ignores_a_window_zeroed_effective_limit(self):
        session = MagicMock()
        session.participants_limit = 30
        data = make_session_data(effective_participants_limit=0, session=session)

        assert data.takes_enrollment is True


def _availability_data(limit: int = 30, **overrides) -> SessionData:
    session = MagicMock()
    session.participants_limit = limit
    return make_session_data(session=session, **overrides)


class TestSessionDataAvailability:
    def test_an_ended_session_wins_over_every_other_term(self):
        data = _availability_data(
            is_ended=True, should_show_as_inactive=True, is_full=True
        )

        assert data.availability == "ended"

    def test_a_session_shut_by_its_end_time_is_in_progress(self):
        data = _availability_data(should_show_as_inactive=True, is_full=True)

        assert data.availability == "in-progress"

    def test_a_session_without_enrollment_leaves_before_the_window_is_asked(self):
        data = _availability_data(limit=0, is_enrollment_available=False, is_full=True)

        assert data.availability == "no-enrollment"


class TestSessionDataSpotsScarce:
    @pytest.mark.parametrize(
        ("limit", "enrolled", "expected"),
        ((10, 8, False), (10, 9, True), (5, 4, False)),
    )
    def test_threshold(self, limit, enrolled, expected):
        data = make_session_data(
            effective_participants_limit=limit, enrolled_count=enrolled
        )

        assert data.spots_scarce is expected

    def test_zero_limit_is_not_scarce(self):
        data = make_session_data(effective_participants_limit=0, enrolled_count=0)

        assert data.spots_scarce is False


class TestSessionDataFilterCategories:
    def test_prepends_public_field_tags(self):
        data = make_session_data(
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

    def test_carries_ticked_public_checkboxes_only(self):
        data = make_session_data(
            field_values=[
                _answer("beginners", "checkbox", value=True),
                _answer("loud", "checkbox", value=False),
                _answer("secret", "checkbox", value=True, is_public=False),
            ]
        )

        assert data.filter_categories == "beginners:true"


class TestSessionDataSearchTerms:
    def test_holds_public_select_values_and_text(self):
        data = make_session_data(
            field_values=[
                _answer("system", "select", value=["D&D", "Homebrew"]),
                _answer("pitch", "text", value="Heist in Lviv"),
                _answer("beginners", "checkbox", value=True),
                _answer("notes", "text", value="secret", is_public=False),
            ]
        )

        assert data.search_terms == "D&D Homebrew Heist in Lviv"

    def test_holds_a_single_selects_bare_answer(self):
        data = make_session_data(
            field_values=[_answer("system", "select", value="D&D")]
        )

        assert data.search_terms == "D&D"
        assert data.public_tag_categories == "system:D&D"


class TestCardPills:
    def test_one_cap_spans_every_field(self):
        data = make_session_data(
            field_values=[
                _answer("system", "select", value=["a", "b", "c"]),
                _answer("beginners", "checkbox", value=True),
                _answer("triggers", "select", value=["one", "two"]),
            ]
        )

        assert data.cloud_pills == [
            CloudPill(icon="system-icon", value="a"),
            CloudPill(icon="system-icon", value="b"),
            CloudPill(icon="system-icon", value="c"),
            CloudPill(icon="beginners-icon", value="Beginners"),
        ]
        assert data.cloud_overflow == [
            CloudPill(icon="triggers-icon", value="one"),
            CloudPill(icon="triggers-icon", value="two"),
        ]

    @pytest.mark.parametrize(
        ("field_type", "value"),
        (("text", "A long pitch"), ("checkbox", False), ("select", "")),
    )
    def test_answer_without_a_pill(self, field_type, value):
        assert field_pills(_answer("f", field_type, value=value)) == []

    def test_a_single_select_answer_earns_its_pill(self):
        data = make_session_data(
            field_values=[_answer("system", "select", value="D&D")]
        )

        assert data.cloud_pills == [CloudPill(icon="system-icon", value="D&D")]

    def test_a_field_kept_off_cards_earns_none(self):
        answer = _answer("system", "select", value=["D&D"])
        data = make_session_data(
            field_values=[answer.model_copy(update={"show_on_cards": False})]
        )

        assert data.card_pills == []


class TestFilterableFlagFields:
    @pytest.mark.parametrize(
        ("ticks", "expected_slugs"),
        (((True, False), ["beginners"]), ((True, True), []), ((False, False), [])),
    )
    def test_offers_a_flag_only_when_it_splits_the_schedule(
        self, ticks, expected_slugs
    ):
        field = OrganizerFieldDTO(
            field_type="checkbox",
            is_public=True,
            name="Beginners",
            order=0,
            pk=1,
            question="",
            slug="beginners",
        )
        cards = [
            make_session_data(
                field_values=[_answer("beginners", "checkbox", value=ticked)]
            )
            for ticked in ticks
        ]

        assert [
            f.slug for f in filterable_flag_fields([field], cards)
        ] == expected_slugs


class TestBuildScheduleDays:
    def test_skips_unscheduled_pending_proposal(self):
        pending = make_session_data(agenda_item=None)
        scheduled = make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=datetime(2026, 7, 10, 12, tzinfo=UTC),
                end_time=datetime(2026, 7, 10, 14, tzinfo=UTC),
                pk=1,
                session_confirmed=True,
            )
        )

        days = build_schedule_days({1: pending, 2: scheduled})

        assert len(days) == 1
        assert [tile.data for tile in days[0].hours[0].tiles] == [scheduled]


class TestBuildCardDays:
    @staticmethod
    def _hour(day: int, hour: int) -> datetime:
        return datetime(2026, 7, day, hour, tzinfo=timezone.get_current_timezone())

    def test_days_split_on_the_local_date_with_kinds_in_state_order(self):
        early = make_session_data()
        late = make_session_data()
        tomorrow = make_session_data()

        days = build_card_days(
            ended={self._hour(10, 12): [early]},
            current={self._hour(10, 10): [late], self._hour(11, 9): [tomorrow]},
            future_unavailable={},
        )

        assert [day.day_start.date().day for day in days] == [10, 11]
        # Within a day the ended group keeps its place ahead of the current
        # one, exactly as the single-day page has always read.
        assert [(slot.kind, slot.hour.hour) for slot in days[0].slots] == [
            ("ended", 12),
            ("current", 10),
        ]
        assert days[1].slots[0].sessions == [tomorrow]
        # The day headings state the dates, so no pill repeats them.
        assert not any(slot.show_date for day in days for slot in day.slots)

    def test_only_the_first_current_slot_is_marked_now(self):
        days = build_card_days(
            ended={},
            current={
                self._hour(10, 10): [make_session_data()],
                self._hour(10, 12): [make_session_data()],
            },
            future_unavailable={self._hour(10, 8): [make_session_data()]},
        )

        assert [
            (slot.kind, slot.is_first_current) for day in days for slot in day.slots
        ] == [("current", True), ("current", False), ("future", False)]
        # A single-day schedule has no day heading, so every pill keeps its date.
        assert all(slot.show_date for slot in days[0].slots)


class TestGroupSessionsByState:
    @staticmethod
    def _future_session(*, participants_limit: int) -> SessionData:
        session = MagicMock()
        session.participants_limit = participants_limit
        start = datetime.now(tz=UTC) + timedelta(days=1)
        return make_session_data(
            agenda_item=AgendaItemDTO(
                start_time=start,
                end_time=start + timedelta(hours=2),
                pk=1,
                session_confirmed=True,
            ),
            is_enrollment_available=False,
            session=session,
        )

    def test_skips_unscheduled_pending_proposal(self):
        pending = make_session_data(agenda_item=None)

        assert group_sessions_by_state({1: pending}) == ({}, {}, {})

    def test_future_session_awaiting_its_window_is_not_yet_available(self):
        closed = self._future_session(participants_limit=10)

        _, current, future_unavailable = group_sessions_by_state({1: closed})

        assert not current
        assert list(future_unavailable.values()) == [[closed]]

    def test_future_session_without_enrollment_stays_in_the_schedule(self):
        no_enrollment = self._future_session(participants_limit=0)

        _, current, future_unavailable = group_sessions_by_state({1: no_enrollment})

        assert list(current.values()) == [[no_enrollment]]
        assert not future_unavailable
