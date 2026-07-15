from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.gates.web.django.chronology.event_presentation import SessionData
from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import AgendaItemDTO, LocationData, SessionDTO
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import EventFactory
from tests.integration.utils import assert_response, assert_response_404


def _url(event, session_id):
    return reverse(
        "web:chronology:session-modal",
        kwargs={"event_slug": event.slug, "session_id": session_id},
    )


def _expected_session_data(*, agenda_item, session, presenter):
    space = agenda_item.space
    return SessionData(
        agenda_item=AgendaItemDTO.model_validate(agenda_item),
        is_enrollment_available=False,
        presenter=UserInfo.from_user_dto(
            UserDTO.model_validate(presenter), gravatar_url=gravatar_url
        ),
        session=SessionDTO.model_validate(session),
        is_full=False,
        full_participant_info="0/10",
        effective_participants_limit=10,
        enrolled_count=0,
        session_participations=[],
        loc=LocationData(
            space_name=space.name,
            parent_slug=space.parent.slug if space.parent else "",
            parent_name=space.parent.name if space.parent else "",
            path=str(space),
        ),
        can_edit=False,
        user_enrolled=False,
        user_waiting=False,
        field_values=[],
        waiting_count=0,
        is_ongoing=False,
        is_ended=False,
    )


class TestSessionModalComponentView:
    def test_renders_modal_for_scheduled_session(
        self, active_user, agenda_item, client, event
    ):
        session = agenda_item.session

        response = client.get(_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/parts/session-modal.html",
            context_data={
                "data": _expected_session_data(
                    agenda_item=agenda_item, session=session, presenter=active_user
                ),
                "event": response.context_data["event"],
                "event_banned": False,
            },
            contains=[session.title, f'id="session-{session.pk}"'],
        )

    def test_unpublished_event_404_for_non_manager(self, agenda_item, client, event):
        event.publication_time = datetime.now(tz=UTC) + timedelta(days=1)
        event.save()

        response = client.get(_url(event, agenda_item.session.pk))

        assert_response_404(response)

    def test_unscheduled_session_404(self, client, event, session):
        response = client.get(_url(event, session.pk))

        assert_response_404(response)

    def test_missing_event_404(self, client, agenda_item):
        url = reverse(
            "web:chronology:session-modal",
            kwargs={
                "event_slug": "does-not-exist",
                "session_id": agenda_item.session.pk,
            },
        )

        response = client.get(url)

        assert_response_404(response)

    @pytest.mark.usefixtures("agenda_item")
    def test_wrong_event_404(self, client, event, session, faker):
        other_event = EventFactory(sphere=event.sphere, slug=faker.slug())

        response = client.get(_url(other_event, session.pk))

        assert_response_404(response)
