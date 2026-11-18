from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.gates.web.django.command_menu import MenuEntry
from ludamus.gates.web.django.create_options import encounter_option, event_option
from ludamus.pacts.encounter import EncountersPolicy
from tests.integration.conftest import (
    EncounterFactory,
    EventFactory,
    SphereFactory,
    UserFactory,
)
from tests.integration.utils import assert_response

URL = reverse("web:command-menu-entries")
TEMPLATE = "components/command-menu-entries.html"


def _event_entry(event):
    return MenuEntry(
        label=event.name,
        href=reverse("panel:event-index", kwargs={"slug": event.slug}),
        when=event.start_time,
    )


def _encounter_entry(encounter):
    return MenuEntry(
        label=encounter.title,
        href=reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        ),
        when=encounter.start_time,
    )


def _assert_entries(response, *, create_options=(), events=(), encounters=()):
    assert_response(
        response,
        HTTPStatus.OK,
        context_data={
            "create_options": tuple(create_options),
            "events": [_event_entry(event) for event in events],
            "encounters": [_encounter_entry(encounter) for encounter in encounters],
        },
        template_name=TEMPLATE,
    )


@pytest.fixture(name="sphere_client")
def sphere_client_fixture(authenticated_client, non_root_sphere):
    authenticated_client.defaults["HTTP_HOST"] = non_root_sphere.site.domain
    return authenticated_client


class TestCommandMenuEntries:
    def test_a_visitor_gets_nothing_to_search(self, client, non_root_sphere):
        EventFactory(sphere=non_root_sphere)
        EncounterFactory(sphere=non_root_sphere, is_public=True)

        response = client.get(URL, HTTP_HOST=non_root_sphere.site.domain)

        _assert_entries(response)

    def test_a_member_finds_their_own_encounters_and_no_events(
        self, sphere_client, active_user, non_root_sphere
    ):
        EventFactory(sphere=non_root_sphere)
        now = datetime.now(UTC)
        older = EncounterFactory(
            sphere=non_root_sphere,
            creator=active_user,
            start_time=now - timedelta(days=3),
        )
        newer = EncounterFactory(
            sphere=non_root_sphere,
            creator=active_user,
            start_time=now + timedelta(days=3),
        )
        EncounterFactory(sphere=non_root_sphere, creator=UserFactory(), is_public=True)

        response = sphere_client.get(URL)

        _assert_entries(
            response, create_options=[encounter_option()], encounters=[newer, older]
        )

    def test_a_manager_finds_the_events_of_this_sphere_alone(
        self, sphere_client, active_user, non_root_sphere
    ):
        non_root_sphere.managers.add(active_user)
        now = datetime.now(UTC)
        older = EventFactory(sphere=non_root_sphere, start_time=now - timedelta(days=9))
        newer = EventFactory(sphere=non_root_sphere, start_time=now + timedelta(days=9))
        elsewhere = SphereFactory()
        elsewhere.managers.add(active_user)
        EventFactory(sphere=elsewhere)

        response = sphere_client.get(URL)

        _assert_entries(
            response,
            create_options=[event_option(), encounter_option()],
            events=[newer, older],
        )

    def test_an_encounter_in_another_sphere_is_left_out(
        self, sphere_client, active_user
    ):
        EncounterFactory(sphere=SphereFactory(), creator=active_user)

        response = sphere_client.get(URL)

        _assert_entries(response, create_options=[encounter_option()])

    def test_encounters_stay_out_where_the_sphere_turned_them_off(
        self, sphere_client, active_user, non_root_sphere
    ):
        EncounterFactory(sphere=non_root_sphere, creator=active_user)
        non_root_sphere.encounters_policy = EncountersPolicy.NONE
        non_root_sphere.save()

        response = sphere_client.get(URL)

        _assert_entries(response)
