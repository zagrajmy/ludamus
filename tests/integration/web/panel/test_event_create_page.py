from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils.timezone import localtime

from ludamus.links.db.django.models import (
    DiscountRule,
    DomainEnrollmentConfig,
    EnrollmentConfig,
    Event,
    EventPanelSettings,
    EventProposalSettings,
    PersonalDataField,
    PersonalDataFieldRequirement,
    ProposalCategory,
    SessionField,
    SessionFieldOption,
    SessionFieldRequirement,
    Space,
    TimeSlot,
    TimeSlotRequirement,
    Track,
)
from ludamus.pacts.discounts import DiscountMethod
from tests.integration.conftest import EventFactory, SphereFactory
from tests.integration.utils import assert_login_required, assert_response

URL = reverse("panel:event-create")
SOURCE_START = datetime(2026, 11, 6, 17, tzinfo=UTC)
NEW_START = datetime(2027, 11, 5, 17, tzinfo=UTC)


def _local(moment):
    return localtime(moment).strftime("%Y-%m-%dT%H:%M")


def _post_data(*, based_on="", slug="mim-2027", start=NEW_START):
    return {
        "name": "MiM 2027",
        "slug": slug,
        "start_time": _local(start),
        "end_time": _local(start + timedelta(hours=8)),
        "based_on": str(based_on),
    }


@pytest.fixture(name="source")
def source_fixture(sphere, active_user):
    source = EventFactory(
        sphere=sphere,
        slug="mim-2026",
        start_time=SOURCE_START,
        end_time=SOURCE_START + timedelta(hours=8),
        address="Piotrkowska 1\nŁódź",
        use_participants_label=True,
    )
    building = Space.objects.create(event=source, name="Pub", slug="pub")
    room = Space.objects.create(event=source, parent=building, name="Hall", slug="hall")
    track = Track.objects.create(event=source, name="RPG", slug="rpg")
    track.spaces.add(room)
    track.managers.add(active_user)
    slot = TimeSlot.objects.create(
        event=source,
        start_time=SOURCE_START,
        end_time=SOURCE_START + timedelta(hours=4),
    )
    system = SessionField.objects.create(
        event=source,
        name="System",
        question="Which system?",
        slug="system",
        field_type="select",
        is_public=True,
        show_on_cards=False,
    )
    SessionFieldOption.objects.create(field=system, label="Trophy", value="trophy")
    pronouns = PersonalDataField.objects.create(
        event=source, name="Pronouns", question="Pronouns?", slug="pronouns"
    )
    category = ProposalCategory.objects.create(
        event=source,
        name="RPG",
        slug="rpg",
        start_time=SOURCE_START - timedelta(days=30),
        end_time=SOURCE_START - timedelta(days=7),
    )
    SessionFieldRequirement.objects.create(category=category, field=system)
    PersonalDataFieldRequirement.objects.create(category=category, field=pronouns)
    TimeSlotRequirement.objects.create(category=category, time_slot=slot)
    EventProposalSettings.objects.create(event=source, description="Bring dice")
    EventPanelSettings.objects.create(
        event=source,
        facilitator_columns=["name", f"field_{pronouns.pk}"],
        proposal_columns=["title", f"field_{system.pk}", "field_999999"],
    )
    enrollment = EnrollmentConfig.objects.create(
        event=source,
        start_time=SOURCE_START - timedelta(days=3),
        end_time=SOURCE_START,
        percentage_slots=50,
    )
    DomainEnrollmentConfig.objects.create(
        enrollment_config=enrollment, domain="example.com", allowed_slots_per_user=2
    )
    DiscountRule.objects.create(
        event=source,
        method=DiscountMethod.SESSION_COUNT,
        quantity=2,
        percent=Decimal("10.00"),
    )
    return source


def _assert_created(response, *, name, url):
    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[
            (messages.SUCCESS, f"Created {name}. It stays hidden until you publish it.")
        ],
        url=url,
    )


class TestEventCreatePageView:
    def test_asks_anonymous_users_to_log_in(self, client):
        assert_login_required(client.get(URL), URL)

    def test_creates_an_empty_event_with_a_default_space(self, panel_client, sphere):
        response = panel_client.post(URL, data=_post_data(slug=""))

        event = Event.objects.get(sphere=sphere)
        _assert_created(response, name="MiM 2027", url=f"/panel/event/{event.slug}/")
        assert event.slug == "mim-2027"
        assert event.publication_time is None
        assert list(event.spaces.values_list("parent", flat=True)) == [None]

    def test_copies_the_setup_of_the_event_it_is_based_on(
        self, panel_client, source, active_user
    ):
        response = panel_client.post(URL, data=_post_data(based_on=source.pk))

        event = Event.objects.get(slug="mim-2027")
        _assert_created(response, name="MiM 2027", url="/panel/event/mim-2027/")
        assert (
            event.address,
            event.use_participants_label,
            event.publication_time,
        ) == (source.address, True, None)
        assert _local(source.proposal_start_time) == "2026-10-27T18:00"
        assert _local(event.proposal_start_time) == "2027-10-26T18:00"
        room = Space.objects.get(event=event, slug="hall")
        assert (room.parent.slug, room.parent.event_id) == ("pub", event.pk)
        track = Track.objects.get(event=event)
        assert list(track.spaces.all()) == [room]
        assert list(track.managers.all()) == [active_user]
        slot = TimeSlot.objects.get(event=event)
        assert slot.start_time == NEW_START
        system = SessionField.objects.get(event=event)
        assert system.show_on_cards is False
        assert list(system.options.values_list("value", flat=True)) == ["trophy"]
        pronouns = PersonalDataField.objects.get(event=event)
        category = ProposalCategory.objects.get(event=event)
        assert category.start_time == NEW_START - timedelta(days=30)
        assert SessionFieldRequirement.objects.get(category=category).field == system
        assert (
            PersonalDataFieldRequirement.objects.get(category=category).field
            == pronouns
        )
        assert TimeSlotRequirement.objects.get(category=category).time_slot == slot
        assert event.proposal_settings.description == "Bring dice"
        assert event.panel_settings.facilitator_columns == [
            "name",
            f"field_{pronouns.pk}",
        ]
        assert event.panel_settings.proposal_columns == ["title", f"field_{system.pk}"]
        enrollment = EnrollmentConfig.objects.get(event=event)
        assert enrollment.end_time == NEW_START
        assert list(enrollment.domain_configs.values_list("domain", flat=True)) == [
            "example.com"
        ]
        assert DiscountRule.objects.filter(event=event).count() == 1
        assert sorted(
            Space.objects.filter(event=source).values_list("slug", flat=True)
        ) == ["hall", "pub"]

    def test_derives_a_polish_aware_slug_from_the_name(self, panel_client, sphere):
        data = _post_data(slug="") | {"name": "Łódzkie Dni Gier"}

        response = panel_client.post(URL, data=data)

        _assert_created(
            response, name="Łódzkie Dni Gier", url="/panel/event/lodzkie-dni-gier/"
        )
        assert Event.objects.filter(sphere=sphere, slug="lodzkie-dni-gier").exists()

    def test_keeps_wall_clock_times_across_a_clock_change(self, panel_client, sphere):
        summer = datetime(2026, 7, 4, 8, tzinfo=UTC)
        source = EventFactory(
            sphere=sphere, start_time=summer, end_time=summer + timedelta(hours=8)
        )
        TimeSlot.objects.create(
            event=source,
            start_time=summer + timedelta(hours=2),
            end_time=summer + timedelta(hours=4),
        )
        winter = datetime(2026, 12, 5, 9, tzinfo=UTC)

        response = panel_client.post(
            URL, data=_post_data(based_on=source.pk, start=winter)
        )

        _assert_created(response, name="MiM 2027", url="/panel/event/mim-2027/")
        slot = TimeSlot.objects.get(event__slug="mim-2027")
        assert localtime(slot.start_time).strftime("%H:%M") == "12:00"

    def test_keeps_a_slot_moved_into_the_spring_gap_after_its_start(
        self, panel_client, sphere
    ):
        june = datetime(2026, 6, 5, 22, 30, tzinfo=UTC)
        source = EventFactory(
            sphere=sphere, start_time=june, end_time=june + timedelta(hours=8)
        )
        TimeSlot.objects.create(
            event=source,
            start_time=june + timedelta(hours=2),
            end_time=june + timedelta(hours=2, minutes=30),
        )
        spring_night = datetime(2027, 3, 27, 23, 30, tzinfo=UTC)

        response = panel_client.post(
            URL, data=_post_data(based_on=source.pk, start=spring_night)
        )

        _assert_created(response, name="MiM 2027", url="/panel/event/mim-2027/")
        slot = TimeSlot.objects.get(event__slug="mim-2027")
        assert slot.end_time - slot.start_time == timedelta(minutes=30)

    def test_gives_a_default_space_to_a_copy_of_an_event_without_one(
        self, panel_client, sphere
    ):
        source = EventFactory(sphere=sphere)

        response = panel_client.post(URL, data=_post_data(based_on=source.pk))

        _assert_created(response, name="MiM 2027", url="/panel/event/mim-2027/")
        assert Space.objects.filter(event__slug="mim-2027", parent=None).count() == 1

    def test_offers_no_event_from_another_sphere_as_the_base(
        self, panel_client, source
    ):
        foreign = EventFactory(sphere=SphereFactory())

        response = panel_client.post(URL, data=_post_data(based_on=foreign.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/event-create.html",
            context_data={"events": [ANY], "form": ANY, "active_nav": "event-create"},
        )
        assert set(Event.objects.values_list("slug", flat=True)) == {
            source.slug,
            foreign.slug,
        }

    def test_keeps_a_taken_slug_for_its_event(self, panel_client, source):
        response = panel_client.post(URL, data=_post_data(slug=source.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/event-create.html",
            context_data={"events": [ANY], "form": ANY, "active_nav": "event-create"},
        )
        assert list(Event.objects.values_list("slug", flat=True)) == [source.slug]

    def test_refuses_an_end_before_the_start(self, panel_client, sphere):
        data = _post_data() | {"end_time": _local(NEW_START - timedelta(hours=1))}

        response = panel_client.post(URL, data=data)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/event-create.html",
            context_data={"events": [], "form": ANY, "active_nav": "event-create"},
        )
        assert not Event.objects.filter(sphere=sphere).exists()
