from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import SphereMembership
from ludamus.pacts.enrollment import SessionParticipationStatus
from ludamus.pacts.event import EventDTO
from ludamus.pacts.parley import ParleyRoomDTO, ParleyRoomKind
from ludamus.pacts.sessions import SessionStatus
from ludamus.pacts.sphere import SphereRole
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SessionParticipationFactory,
    SphereFactory,
)
from tests.integration.utils import assert_response, assert_response_404
from tests.integration.web.parley.helpers import configure_parley

CHATS_URL = reverse("multiverse:panel:chats")


def _chat_url(kind, pk):
    return reverse("multiverse:panel:chat", kwargs={"kind": kind, "pk": pk})


def _room(session, *, kind=ParleyRoomKind.SESSION):
    event = session.event
    return ParleyRoomDTO(
        kind=kind,
        sphere_id=event.sphere_id,
        pk=session.pk,
        event_pk=event.pk,
        title=session.title,
        can_write=True,
        can_moderate=True,
        moderating=True,
        event_title=event.name,
        event_slug=event.slug,
        starts_at=int(event.start_time.timestamp()),
        ends_at=int(event.end_time.timestamp()),
    )


def _context(event, *, rooms, room=None):
    event_dto = EventDTO.model_validate(event)
    return {
        "events": [event_dto],
        "current_event": event_dto,
        "is_proposal_active": event_dto.is_proposal_active,
        "active_nav": "chats",
        "rooms": rooms,
        "room": room,
    }


@pytest.fixture(name="parley_settings")
def parley_settings_fixture(settings):
    return configure_parley(settings)


@pytest.fixture(name="programme")
def programme_fixture(active_user, event):
    played = SessionFactory(
        event=event, category=None, title="Mothership", status=SessionStatus.ACCEPTED
    )
    SessionParticipationFactory(
        session=played, user=active_user, status=SessionParticipationStatus.CONFIRMED
    )
    watched = SessionFactory(
        event=event,
        category=None,
        title="Ticket to Ride",
        status=SessionStatus.ACCEPTED,
    )
    return played, watched


@pytest.mark.usefixtures("parley_settings")
class TestChatModerationPageView:
    def test_lists_only_the_sphere_s_chats_the_manager_is_not_in(
        self, authenticated_client, active_user, sphere, event, programme
    ):
        sphere.managers.add(active_user)
        _played, watched = programme
        elsewhere = EventFactory(sphere=SphereFactory())
        elsewhere.sphere.managers.add(active_user)
        SessionFactory(event=elsewhere, category=None, status=SessionStatus.ACCEPTED)

        response = authenticated_client.get(CHATS_URL)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="sphere/panel/chats.html",
            context_data=_context(event, rooms=[_room(watched)]),
        )

    def test_opens_one_of_those_chats(
        self, authenticated_client, active_user, sphere, event, programme
    ):
        sphere.managers.add(active_user)
        _played, watched = programme

        response = authenticated_client.get(_chat_url("session", watched.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="sphere/panel/chats.html",
            context_data=_context(event, rooms=[_room(watched)], room=_room(watched)),
        )

    @pytest.mark.parametrize("which", ("own", "foreign", "wrong-kind"))
    def test_a_chat_off_that_list_is_not_found(
        self, authenticated_client, active_user, sphere, programme, which
    ):
        sphere.managers.add(active_user)
        played, watched = programme
        foreign_event = EventFactory(sphere=SphereFactory())
        foreign_event.sphere.managers.add(active_user)
        foreign = SessionFactory(
            event=foreign_event, category=None, status=SessionStatus.ACCEPTED
        )
        kind, pk = {
            "own": ("session", played.pk),
            "foreign": ("session", foreign.pk),
            "wrong-kind": ("event", watched.pk),
        }[which]

        response = authenticated_client.get(_chat_url(kind, pk))

        assert_response_404(response)

    def test_a_role_that_does_not_moderate_chats_is_not_found(
        self, authenticated_client, active_user, sphere, programme
    ):
        SphereMembership.objects.create(
            sphere=sphere, user=active_user, role=SphereRole.COMMS
        )
        _played, watched = programme

        response = authenticated_client.get(_chat_url("session", watched.pk))

        assert_response_404(response)


@pytest.mark.usefixtures("parley_settings", "programme")
class TestBootstrapModerationLink:
    def test_points_a_manager_to_the_sphere_s_moderation_page(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(reverse("parley_bootstrap"))

        assert response.json()["moderation"] == {"sphere": sphere.pk, "url": CHATS_URL}

    def test_leaves_it_out_for_someone_who_moderates_nothing_here(
        self, authenticated_client
    ):
        response = authenticated_client.get(reverse("parley_bootstrap"))

        assert response.json()["moderation"] is None
