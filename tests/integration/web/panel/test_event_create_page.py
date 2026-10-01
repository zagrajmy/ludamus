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
SHIFT = NEW_START - SOURCE_START


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


class TestEventCreatePageView:
    def test_asks_anonymous_users_to_log_in(self, client):
        assert_login_required(client.get(URL), URL)

    def test_offers_the_latest_event_as_the_base(self, panel_client, source, sphere):
        EventFactory(sphere=sphere, start_time=SOURCE_START - timedelta(days=365))

        response = panel_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/event-create.html",
            context_data={"events": ANY, "form": ANY, "active_nav": "event-create"},
        )
        assert response.context["form"]["based_on"].initial == source.pk

    def test_creates_an_empty_event_with_a_default_space(self, panel_client, sphere):
        response = panel_client.post(URL, data=_post_data(slug=""))

        event = Event.objects.get(sphere=sphere)
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "Created MiM 2027. It stays hidden until you publish it.",
                )
            ],
            url=f"/panel/event/{event.slug}/",
        )
        assert event.slug == "mim-2027"
        assert event.publication_time is None
        assert list(event.spaces.values_list("parent", flat=True)) == [None]

    def test_copies_the_setup_of_the_event_it_is_based_on(
        self, panel_client, source, active_user
    ):
        response = panel_client.post(URL, data=_post_data(based_on=source.pk))

        event = Event.objects.get(slug="mim-2027")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[
                (
                    messages.SUCCESS,
                    "Created MiM 2027. It stays hidden until you publish it.",
                )
            ],
            url="/panel/event/mim-2027/",
        )
        assert (
            event.address,
            event.use_participants_label,
            event.publication_time,
        ) == (source.address, True, None)
        assert event.proposal_start_time == source.proposal_start_time + SHIFT
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

    def test_refuses_an_event_from_another_sphere_as_the_base(self, panel_client):
        foreign = EventFactory(sphere=SphereFactory())

        response = panel_client.post(URL, data=_post_data(based_on=foreign.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/event-create.html",
            context_data={"events": [], "form": ANY, "active_nav": "event-create"},
        )
        assert response.context["form"].errors == {
            "based_on": [
                (
                    f"Select a valid choice. {foreign.pk} is not one of the available"
                    " choices."
                )
            ]
        }
        assert not Event.objects.filter(slug="mim-2027").exists()

    def test_reports_a_slug_taken_in_the_sphere(self, panel_client, source):
        response = panel_client.post(URL, data=_post_data(slug=source.slug))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/event-create.html",
            context_data={"events": ANY, "form": ANY, "active_nav": "event-create"},
        )
        assert response.context["form"].errors == {
            "slug": ["Another event in this sphere uses this slug."]
        }
        assert Event.objects.filter(slug=source.slug).count() == 1

    def test_refuses_an_end_before_the_start(self, panel_client):
        data = _post_data() | {"end_time": _local(NEW_START - timedelta(hours=1))}

        response = panel_client.post(URL, data=data)

        assert response.context["form"].errors == {
            "end_time": ["End time must be after start time."]
        }
        assert not Event.objects.filter(slug="mim-2027").exists()
