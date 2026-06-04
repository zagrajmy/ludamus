from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.sites.models import Site
from factory import Faker, LazyAttribute, SubFactory
from factory.django import DjangoModelFactory
from pytest_factoryboy import register

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Area,
    Encounter,
    EncounterRSVP,
    EnrollmentConfig,
    Event,
    ProposalCategory,
    Session,
    SessionParticipation,
    SessionParticipationStatus,
    Space,
    Sphere,
    Tag,
    TagCategory,
    TimeSlot,
    Venue,
)
from tests.integration.factories import AnonymousUserFactory, CompleteUserFactory

User = get_user_model()


pytest.register_assert_rewrite("tests.integration.utils")

register(CompleteUserFactory)
register(AnonymousUserFactory)


@pytest.fixture(autouse=True)
def _django_db(transactional_db):
    pass


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = Faker("user_name")
    email = Faker("email")
    name = Faker("name")
    slug = LazyAttribute(lambda o: o.username)
    user_type = "active"  # Use the actual choice value
    is_active = True
    is_staff = False
    is_superuser = False


class SiteFactory(DjangoModelFactory):
    class Meta:
        model = Site
        django_get_or_create = ("domain",)

    domain = LazyAttribute(lambda o: f"{o.name.lower().replace(' ', '-')}.testserver")
    name = Faker("company")


class SphereFactory(DjangoModelFactory):
    class Meta:
        model = Sphere

    name = Faker("company")
    site = SubFactory(SiteFactory)


class EventFactory(DjangoModelFactory):
    class Meta:
        model = Event

    name = Faker("sentence", nb_words=4)
    slug = Faker("slug")
    description = Faker("text")
    sphere = SubFactory(SphereFactory)
    start_time = LazyAttribute(lambda __: datetime.now(UTC) + timedelta(days=7))
    end_time = LazyAttribute(lambda o: o.start_time + timedelta(hours=8))
    publication_time = LazyAttribute(lambda __: datetime.now(UTC) - timedelta(days=14))
    proposal_start_time = LazyAttribute(lambda o: o.start_time - timedelta(days=10))
    proposal_end_time = LazyAttribute(lambda o: o.start_time - timedelta(days=6))


class EnrollmentConfigFactory(DjangoModelFactory):
    class Meta:
        model = EnrollmentConfig

    event = SubFactory(EventFactory)
    start_time = LazyAttribute(lambda o: o.event.start_time - timedelta(days=5))
    end_time = LazyAttribute(lambda o: o.event.start_time - timedelta(days=1))
    percentage_slots = 100


class VenueFactory(DjangoModelFactory):
    class Meta:
        model = Venue

    name = Faker("company")
    slug = Faker("slug")
    event = SubFactory(EventFactory)
    order = 0


class AreaFactory(DjangoModelFactory):
    class Meta:
        model = Area

    name = Faker("word")
    slug = Faker("slug")
    venue = SubFactory(VenueFactory)
    order = 0


class SpaceFactory(DjangoModelFactory):
    class Meta:
        model = Space

    name = Faker("word")
    slug = Faker("slug")
    area = SubFactory(AreaFactory)


class TimeSlotFactory(DjangoModelFactory):
    class Meta:
        model = TimeSlot

    event = SubFactory(EventFactory)
    start_time = LazyAttribute(lambda o: o.event.start_time)
    end_time = LazyAttribute(lambda o: o.start_time + timedelta(hours=2))


class TagCategoryFactory(DjangoModelFactory):
    class Meta:
        model = TagCategory

    name = Faker("word")
    slug = Faker("slug")
    event = SubFactory(EventFactory)
    category_type = "SELECT"
    icon = "dice"


class TagFactory(DjangoModelFactory):
    class Meta:
        model = Tag

    name = Faker("word")
    slug = Faker("slug")
    category = SubFactory(TagCategoryFactory)


class SessionFactory(DjangoModelFactory):
    class Meta:
        model = Session

    title = Faker("sentence", nb_words=5)
    slug = Faker("slug")
    description = Faker("text")
    presenter = SubFactory(UserFactory)
    display_name = Faker("name")
    contact_email = Faker("email")
    category = SubFactory("tests.integration.conftest.ProposalCategoryFactory")
    participants_limit = Faker("random_int", min=2, max=20)
    sphere = SubFactory(SphereFactory)
    status = "pending"


class SessionParticipationFactory(DjangoModelFactory):
    class Meta:
        model = SessionParticipation

    user = SubFactory(UserFactory)
    session = SubFactory(SessionFactory)
    status = SessionParticipationStatus.CONFIRMED.value
    enrolled_by = LazyAttribute(lambda o: o.user)


class ProposalCategoryFactory(DjangoModelFactory):
    class Meta:
        model = ProposalCategory

    name = Faker("word")
    slug = Faker("slug")
    event = SubFactory(EventFactory)
    max_participants_limit = 20
    min_participants_limit = 2


class EncounterFactory(DjangoModelFactory):
    class Meta:
        model = Encounter

    title = Faker("sentence", nb_words=4)
    description = Faker("text")
    game = Faker("word")
    sphere = SubFactory(SphereFactory)
    creator = SubFactory(UserFactory)
    start_time = LazyAttribute(lambda __: datetime.now(UTC) + timedelta(days=7))
    end_time = LazyAttribute(lambda o: o.start_time + timedelta(hours=3))
    place = Faker("city")
    max_participants = 6
    share_code = LazyAttribute(lambda __: token_urlsafe(4)[:6])


class EncounterRSVPFactory(DjangoModelFactory):
    class Meta:
        model = EncounterRSVP

    encounter = SubFactory(EncounterFactory)
    user = SubFactory(UserFactory)
    ip_address = Faker("ipv4")


class AgendaItemFactory(DjangoModelFactory):
    class Meta:
        model = AgendaItem

    session = SubFactory(SessionFactory)
    space = SubFactory(SpaceFactory)
    start_time = LazyAttribute(lambda __: datetime.now(UTC) + timedelta(days=7))
    end_time = LazyAttribute(lambda o: o.start_time + timedelta(hours=2))


@pytest.fixture
def authenticated_client(client, active_user):
    client.force_login(active_user)
    return client


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


@pytest.fixture(name="active_user")
def active_user_fixture():
    return UserFactory(
        username="testuser",
        email="testuser@example.com",
        name="Test User",
        password=make_password(None),
    )


@pytest.fixture
def connected_user(active_user):
    return UserFactory(
        username="connecteduser",
        email="connected@example.com",
        user_type="connected",
        manager=active_user,
        password=make_password(None),
    )


@pytest.fixture(name="staff_user")
def staff_user_fixture():
    return UserFactory(username="staffuser", is_staff=True)


@pytest.fixture
def waiter():
    return UserFactory(
        username="waiter",
        email="waiter@example.com",
        name="Wendy Waiter",
        password=make_password(None),
    )


@pytest.fixture
def non_root_sphere(settings, faker):
    name = faker.word()
    site = Site.objects.create(
        domain=f"{name}.{settings.ROOT_DOMAIN}", name=name.title()
    )
    return SphereFactory(site=site, name=site.name)


@pytest.fixture(name="event")
def event_fixture(sphere):
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return EventFactory(
        sphere=sphere,
        start_time=midnight,
        end_time=midnight + timedelta(hours=23, minutes=59, seconds=59),
        proposal_start_time=now - timedelta(days=10),
        proposal_end_time=now - timedelta(days=3),
    )


@pytest.fixture(name="enrollment_config")
def enrollment_config_fixture(event):
    now = datetime.now(UTC)
    return EnrollmentConfigFactory(
        event=event,
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=5),
        percentage_slots=100,
    )


@pytest.fixture(name="venue")
def venue_fixture(event):
    return VenueFactory(event=event, name="Main Venue")


@pytest.fixture(name="area")
def area_fixture(venue):
    return AreaFactory(venue=venue, name="Main Area")


@pytest.fixture(name="space")
def space_fixture(area):
    return SpaceFactory(area=area)


@pytest.fixture
def time_slot(event):
    return TimeSlotFactory(
        event=event,
        start_time=event.start_time,
        end_time=event.start_time + timedelta(hours=2),
    )


@pytest.fixture(name="session")
def session_fixture(active_user, sphere):
    return SessionFactory(
        presenter=active_user,
        display_name=active_user.full_name,
        sphere=sphere,
        participants_limit=10,
        min_age=0,
    )


@pytest.fixture(name="proposal_category")
def proposal_category_fixture(event):
    return ProposalCategoryFactory(event=event)


@pytest.fixture(name="pending_session")
def pending_session_fixture(proposal_category, active_user, sphere):
    return SessionFactory(
        category=proposal_category,
        presenter=active_user,
        display_name=active_user.name,
        sphere=sphere,
        participants_limit=10,
        min_age=0,
        status="pending",
    )


@pytest.fixture
def agenda_item(session, space):
    return AgendaItemFactory(session=session, space=space)


@pytest.fixture(autouse=True, name="sphere")
def sphere_fixture(settings, transactional_db):  # noqa: ARG001
    site, __ = Site.objects.update_or_create(
        domain=settings.ROOT_DOMAIN, defaults={"name": settings.ROOT_DOMAIN}
    )
    return SphereFactory(site=site, name=site.name)


@pytest.fixture(name="faker")
def faker_fixture():
    from faker import Faker as FakerLib  # noqa: PLC0415

    fake = FakerLib()
    # Wrap date_time methods to always include UTC timezone
    original_date_time_between = fake.date_time_between

    def date_time_between_tz(*args, **kwargs):
        kwargs.setdefault("tzinfo", UTC)
        return original_date_time_between(*args, **kwargs)

    fake.date_time_between = date_time_between_tz
    return fake


@pytest.fixture(name="user")
def user_fixture(active_user):
    return active_user


@pytest.fixture(name="encounter")
def encounter_fixture(sphere):
    return EncounterFactory(sphere=sphere)


@pytest.fixture
def encounter_with_rsvps(sphere):
    encounter = EncounterFactory(sphere=sphere, max_participants=6)
    EncounterRSVPFactory(encounter=encounter)
    EncounterRSVPFactory(encounter=encounter)
    return encounter
