from datetime import datetime

import pytest
from django.core.exceptions import ValidationError

from ludamus.adapters.db.django.models import (
    DEFAULT_NAME,
    AgendaItem,
    Area,
    Connection,
    DomainEnrollmentConfig,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    EventProposalSettings,
    EventSettings,
    Facilitator,
    HostPersonalData,
    PersonalDataField,
    PersonalDataFieldOption,
    PersonalDataFieldRequirement,
    ProposalCategory,
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
    Space,
    Sphere,
    Tag,
    TagCategory,
    TimeSlot,
    TimeSlotRequirement,
    Track,
    User,
    UserEnrollmentConfig,
    Venue,
)


class TestSphere:
    def test_str(self, faker):
        name = faker.word()

        assert str(Sphere(name=name)) == name


class TestConnection:
    def test_str(self, faker):
        display_name = faker.word()

        assert str(Connection(display_name=display_name)) == display_name


class TestEnrollmentConfig:
    def test_str(self, faker):
        name = faker.word()

        assert (
            str(EnrollmentConfig(event=Event(name=name)))
            == f"Enrollment config for {name}"
        )


class TestEventSettings:
    def test_str(self, faker):
        name = faker.word()

        assert str(EventSettings(event=Event(name=name))) == f"Settings for {name}"


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


class TestVenue:
    def test_str(self, faker):
        name = faker.word()

        assert str(Venue(name=name)) == name


class TestArea:
    def test_str(self, faker):
        venue_name = faker.word()
        area_name = faker.word()

        area = Area(name=area_name, venue=Venue(name=venue_name))

        assert str(area) == f"{venue_name} > {area_name}"


class TestSpace:
    def test_str(self, faker):
        venue_name = faker.word()
        area_name = faker.word()
        space_name = faker.word()

        venue = Venue(name=venue_name)
        area = Area(name=area_name, venue=venue)
        space = Space(name=space_name, area=area)

        assert str(space) == f"{venue_name} > {area_name} > {space_name}"


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


class TestTagCategory:
    def test_str(self, faker):
        name = faker.word()

        assert str(TagCategory(name=name)) == name


class TestTag:
    def test_str(self, faker):
        name = faker.word()

        assert str(Tag(name=name)) == name


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
                    session=Session(title=title, display_name=name),
                )
            )
            == f"{title} by {name} (True)"
        )


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

    def test_initials_from_name(self):
        user = User(name="John Doe")

        assert user.initials == "JD"

    def test_initials_from_single_name(self):
        user = User(name="John")

        assert user.initials == "J"

    def test_initials_from_three_names(self):
        user = User(name="John Michael Doe")

        assert user.initials == "JM"  # Only first two

    def test_initials_fallback_to_username(self):
        user = User(name="", username="johndoe")

        assert user.initials == "J"

    def test_initials_empty_returns_question_mark(self):
        user = User(name="", username="")

        assert user.initials == "?"

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


class TestPersonalDataFieldRequirement:
    def test_str_required(self, faker):
        field_name = faker.word()
        category_name = faker.word()

        requirement = PersonalDataFieldRequirement(
            field=PersonalDataField(name=field_name),
            category=ProposalCategory(name=category_name),
            is_required=True,
        )

        assert str(requirement) == f"{field_name} (required) for {category_name}"

    def test_str_optional(self, faker):
        field_name = faker.word()
        category_name = faker.word()

        requirement = PersonalDataFieldRequirement(
            field=PersonalDataField(name=field_name),
            category=ProposalCategory(name=category_name),
            is_required=False,
        )

        assert str(requirement) == f"{field_name} (optional) for {category_name}"


class TestHostPersonalData:
    def test_str(self, faker):
        field_name = faker.word()
        value = faker.sentence()

        data = HostPersonalData(field=PersonalDataField(name=field_name), value=value)

        assert str(data) == f"{field_name}: {value[:50]}"

    def test_str_truncates_long_value(self, faker):
        field_name = faker.word()
        value = "x" * 100

        data = HostPersonalData(field=PersonalDataField(name=field_name), value=value)

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

        assert str(sfv) == f"{field_name}: {value}"


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
