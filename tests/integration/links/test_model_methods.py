from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from ludamus.links.db.django.models import (
    DEFAULT_NAME,
    AgendaItem,
    Connection,
    DomainEnrollmentConfig,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    EventBan,
    EventIntegration,
    EventProposalSettings,
    Facilitator,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldValue,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
    Shadowban,
    Space,
    Sphere,
    TimeSlot,
    TimeSlotRequirement,
    Track,
    User,
    UserEnrollmentConfig,
)
from tests.integration.conftest import AgendaItemFactory, SessionFactory, UserFactory

_MIDNIGHT = datetime(2026, 6, 1, tzinfo=UTC)
_CANDIDATE_START, _CANDIDATE_END = 10, 12
# NOTE: windows are half-open, so touching ends do not overlap.
_WINDOWS = (
    pytest.param(9, 13, True, id="contains"),
    pytest.param(10.5, 11.5, True, id="inside"),
    pytest.param(9, 11, True, id="ends-inside"),
    pytest.param(11, 13, True, id="starts-inside"),
    pytest.param(10, 12, True, id="same-window"),
    pytest.param(8, 10, False, id="ends-as-it-starts"),
    pytest.param(12, 14, False, id="starts-as-it-ends"),
)


def _at(hour: float) -> datetime:
    return _MIDNIGHT + timedelta(hours=hour)


class TestSphere:
    def test_str(self, faker):
        name = faker.word()

        assert str(Sphere(name=name)) == name


class TestConnection:
    def test_str(self, faker):
        display_name = faker.word()

        assert str(Connection(display_name=display_name)) == display_name


class TestEventIntegration:
    def test_str(self, faker):
        display_name = faker.word()

        assert str(EventIntegration(display_name=display_name)) == display_name


class TestEnrollmentConfig:
    def test_str(self, faker):
        name = faker.word()

        assert (
            str(EnrollmentConfig(event=Event(name=name)))
            == f"Enrollment config for {name}"
        )


class TestEventProposalSettings:
    def test_str(self, faker):
        name = faker.word()

        assert (
            str(EventProposalSettings(event=Event(name=name)))
            == f"Proposal settings for {name}"
        )


class TestUserEnrollmentConfig:
    def test_str(self, faker):
        email = faker.email()
        allowed_slots = faker.random_int(min=1)

        assert (
            str(UserEnrollmentConfig(user_email=email, allowed_slots=allowed_slots))
            == f"{email}: {allowed_slots} people enrollment limit"
        )


class TestDomainEnrollmentConfig:
    def test_str(self, faker):
        domain = faker.domain_name()
        slots = faker.random_int(min=1, max=100)

        assert str(
            DomainEnrollmentConfig(domain=domain, allowed_slots_per_user=slots)
        ) == (f"@{domain}: {slots} people enrollment limit per account")

    def test_clean(self):
        DomainEnrollmentConfig(
            enrollment_config=EnrollmentConfig(),
            domain="example.com",
            allowed_slots_per_user=1,
        ).clean()

    def test_clean_empty_domain(self):
        DomainEnrollmentConfig(
            enrollment_config=EnrollmentConfig(), domain="", allowed_slots_per_user=1
        ).clean()

    def test_clean_wrong_domain(self):
        with pytest.raises(ValidationError):
            DomainEnrollmentConfig(
                enrollment_config=EnrollmentConfig(),
                domain="examplecom",
                allowed_slots_per_user=1,
            ).clean()


class TestFacilitator:
    def test_str(self, faker):
        display_name = faker.name()

        assert str(Facilitator(display_name=display_name)) == display_name


class TestSpace:
    def test_str_root(self, faker):
        name = faker.word()

        assert str(Space(name=name)) == name

    def test_str_nested(self, faker):
        root_name = faker.word()
        mid_name = faker.word()
        leaf_name = faker.word()

        root = Space(name=root_name)
        mid = Space(name=mid_name, parent=root)
        leaf = Space(name=leaf_name, parent=mid)

        assert str(leaf) == f"{root_name} > {mid_name} > {leaf_name}"


class TestTimeSlot:
    def test_str(self, faker, time_zone):
        pk = faker.random_int(min=1)

        assert (
            str(
                TimeSlot(
                    id=pk,
                    start_time=datetime(2025, 1, 2, 3, 4, tzinfo=time_zone),
                    end_time=datetime(2025, 1, 2, 5, 6, tzinfo=time_zone),
                )
            )
            == f"2025-01-02 03:04 - 05:06 ({pk})"
        )

    def test_str_different_days(self, faker, time_zone):
        pk = faker.random_int(min=1)

        assert (
            str(
                TimeSlot(
                    id=pk,
                    start_time=datetime(2025, 1, 2, 3, 4, tzinfo=time_zone),
                    end_time=datetime(2025, 5, 6, 7, 8, tzinfo=time_zone),
                )
            )
            == f"2025-01-02 03:04 - 2025-05-06 07:08 ({pk})"
        )


class TestSession:
    def test_str(self, faker):
        title = faker.word()

        assert str(Session(title=title)) == title


class TestAgendaItem:
    def test_str(self, faker):
        title = faker.sentence()
        name = faker.name()

        assert (
            str(
                AgendaItem(
                    session_confirmed=True,
                    session=Session(title=title, facilitator_name=name),
                )
            )
            == f"{title} by {name} (True)"
        )

    @pytest.mark.parametrize(("start_hour", "end_hour", "overlaps"), _WINDOWS)
    def test_overlaps_with_agrees_from_either_side(
        self, *, start_hour: float, end_hour: float, overlaps: bool
    ):
        item = AgendaItem(
            start_time=_at(_CANDIDATE_START), end_time=_at(_CANDIDATE_END)
        )
        other = AgendaItem(start_time=_at(start_hour), end_time=_at(end_hour))

        assert (item.overlaps_with(other), other.overlaps_with(item)) == (
            overlaps,
            overlaps,
        )


class TestSessionManagerConflictedUserIds:
    @staticmethod
    def _scheduled(event, *, start_hour: float, end_hour: float) -> Session:
        return AgendaItemFactory(
            session=SessionFactory(event=event, category=None),
            start_time=_at(start_hour),
            end_time=_at(end_hour),
        ).session

    @pytest.mark.parametrize(("start_hour", "end_hour", "conflicts"), _WINDOWS)
    def test_a_confirmed_seat_conflicts_exactly_when_the_windows_overlap(
        self, event, *, start_hour: float, end_hour: float, conflicts: bool
    ):
        candidate = self._scheduled(
            event, start_hour=_CANDIDATE_START, end_hour=_CANDIDATE_END
        )
        other = self._scheduled(event, start_hour=start_hour, end_hour=end_hour)
        user = UserFactory()
        SessionParticipation.objects.create(
            session=other, user=user, status=SessionParticipationStatus.CONFIRMED
        )

        result = Session.objects.conflicted_user_ids(candidate, [user.pk])

        assert result == ({user.pk} if conflicts else set())

    def test_only_confirmed_seats_of_the_asked_users_conflict(self, event):
        candidate = self._scheduled(
            event, start_hour=_CANDIDATE_START, end_hour=_CANDIDATE_END
        )
        containing = self._scheduled(event, start_hour=9, end_hour=13)
        seated, waiting, unasked = UserFactory(), UserFactory(), UserFactory()
        for user, status in (
            (seated, SessionParticipationStatus.CONFIRMED),
            (waiting, SessionParticipationStatus.WAITING),
            (unasked, SessionParticipationStatus.CONFIRMED),
        ):
            SessionParticipation.objects.create(
                session=containing, user=user, status=status
            )

        result = Session.objects.conflicted_user_ids(candidate, [seated.pk, waiting.pk])

        assert result == {seated.pk}


class TestProposalCategory:
    def test_str(self, faker):
        name = faker.word()
        pk = faker.random_int(min=1)

        assert str(ProposalCategory(name=name, id=pk)) == f"{name} ({pk})"


class TestSessionParticipation:
    def test_str(self, faker):
        username = faker.user_name()
        title = faker.word()

        assert (
            str(
                SessionParticipation(
                    user=User(name=username),
                    status=SessionParticipationStatus.CONFIRMED,
                    session=Session(title=title),
                )
            )
            == f"{username} confirmed on {title}"
        )


class TestUser:
    def test_get_full_name_no_name(self):
        user = User()

        assert user.get_full_name() == DEFAULT_NAME

    def test_get_full_name(self, faker):
        user = User(name=faker.name())

        assert user.get_full_name() == user.name

    def test_str(self):
        user = User(name="John Smith", email="johnny@example.com")

        assert str(user) == "John Smith <johnny@example.com>"


class TestPersonalDataField:
    def test_str(self, faker):
        name = faker.word()

        assert str(PersonalDataField(name=name)) == name


class TestPersonalDataFieldOption:
    def test_str(self, faker):
        label = faker.word()

        assert str(PersonalDataFieldOption(label=label)) == label


class TestPersonalDataFieldValue:
    def test_str(self, faker):
        field_name = faker.word()
        value = faker.sentence()

        data = PersonalDataFieldValue(
            field=PersonalDataField(name=field_name), value=value
        )

        assert str(data) == f"{field_name}: {value[:50]}"

    def test_str_truncates_long_value(self, faker):
        field_name = faker.word()
        value = "x" * 100

        data = PersonalDataFieldValue(
            field=PersonalDataField(name=field_name), value=value
        )

        assert str(data) == f"{field_name}: {'x' * 50}"


class TestSessionField:
    def test_str(self, faker):
        name = faker.word()

        assert str(SessionField(name=name)) == name


class TestSessionFieldOption:
    def test_str(self, faker):
        label = faker.word()

        assert str(SessionFieldOption(label=label)) == label


class TestSessionFieldValue:
    def test_str(self, faker):
        field_name = faker.word()
        value = faker.sentence()

        sfv = SessionFieldValue(field=SessionField(name=field_name), value=value)

        assert str(sfv) == f"{field_name}: {value[:50]}"

    def test_str_truncates_long_value(self, faker):
        field_name = faker.word()
        value = "x" * 100

        sfv = SessionFieldValue(field=SessionField(name=field_name), value=value)

        assert str(sfv) == f"{field_name}: {'x' * 50}"


class TestTimeSlotRequirement:
    def test_str_required(self, faker):
        category_name = faker.word()

        requirement = TimeSlotRequirement(
            category=ProposalCategory(name=category_name), is_required=True
        )

        assert str(requirement) == f"Time slot (required) for {category_name}"

    def test_str_optional(self, faker):
        category_name = faker.word()

        requirement = TimeSlotRequirement(
            category=ProposalCategory(name=category_name), is_required=False
        )

        assert str(requirement) == f"Time slot (optional) for {category_name}"


class TestEncounter:
    def test_str(self, faker):
        title = faker.word()

        assert str(Encounter(title=title)) == title


class TestEncounterRSVP:
    def test_str(self):
        user = User(name="John Smith", email="john@example.com")

        assert str(EncounterRSVP(user=user)) == str(user)


class TestSessionFieldRequirement:
    def test_str_required(self, faker):
        field_name = faker.word()
        category_name = faker.word()

        requirement = SessionFieldRequirement(
            field=SessionField(name=field_name),
            category=ProposalCategory(name=category_name),
            is_required=True,
        )

        assert str(requirement) == f"{field_name} (required) for {category_name}"

    def test_str_optional(self, faker):
        field_name = faker.word()
        category_name = faker.word()

        requirement = SessionFieldRequirement(
            field=SessionField(name=field_name),
            category=ProposalCategory(name=category_name),
            is_required=False,
        )

        assert str(requirement) == f"{field_name} (optional) for {category_name}"


class TestTrack:
    def test_str(self, faker):
        name = faker.word()

        assert str(Track(name=name)) == name


class TestShadowban:
    def test_str(self):
        assert str(Shadowban(owner_id=1, target_id=2)) == "1 shadowbanned 2"


class TestEventBan:
    def test_str(self):
        assert str(EventBan(user_id=3, event_id=4)) == "3 banned from event 4"
