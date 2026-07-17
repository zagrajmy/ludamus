from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.urls import reverse

from ludamus.gates.web.django.chronology.event_presentation import SessionData
from ludamus.gates.web.django.entities import UserInfo
from ludamus.links.db.django.models import (
    SessionField,
    SessionFieldValue,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.links.gravatar import gravatar_url
from ludamus.pacts import AgendaItemDTO, EventDTO, LocationData, SessionDTO
from ludamus.pacts.crowd import UserDTO
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    SessionFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404

_TEMPLATE = "chronology/parts/session-modal.html"


def _url(event, session_id):
    return reverse(
        "web:chronology:session-modal",
        kwargs={"event_slug": event.slug, "session_id": session_id},
    )


def _activate_anonymous(client, *, sphere, event, code, settings, site_id=None):
    session = client.session
    session["anonymous_enrollment_active"] = True
    session["anonymous_site_id"] = sphere.site.id if site_id is None else site_id
    session["anonymous_event_id"] = event.id
    session["anonymous_user_code"] = code
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


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
                "event": EventDTO.model_validate(event),
                "event_banned": False,
            },
            contains=[session.title, f'id="session-{session.pk}"'],
        )

    def test_unpublished_event_404_for_non_manager(self, agenda_item, client, event):
        event.publication_time = datetime.now(tz=UTC) + timedelta(days=1)
        event.save()

        response = client.get(_url(event, agenda_item.session.pk))

        assert_response_404(response)

    def test_unpublished_event_ok_for_manager(
        self, authenticated_client, active_user, sphere, agenda_item, event
    ):
        sphere.managers.add(active_user)
        event.publication_time = datetime.now(tz=UTC) + timedelta(days=1)
        event.save()

        response = authenticated_client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/parts/session-modal.html",
            context_data=ANY,
            contains=f'id="session-{agenda_item.session.pk}"',
        )

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

    def test_renders_public_field_values(self, agenda_item, client, event):
        session = agenda_item.session
        select_field = SessionField.objects.create(
            event=event,
            name="Genre",
            question="Genre",
            slug="genre",
            field_type="select",
            is_multiple=True,
            is_public=True,
            icon="puzzle-piece",
        )
        text_field = SessionField.objects.create(
            event=event,
            name="Notes",
            question="Notes",
            slug="notes",
            field_type="text",
            is_public=True,
        )
        SessionFieldValue.objects.create(
            session=session, field=select_field, value=["RPG", "Horror"]
        )
        SessionFieldValue.objects.create(
            session=session, field=text_field, value="Bring dice"
        )

        response = client.get(_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["Genre", "RPG", "Horror", "Notes", "Bring dice"],
        )

    def test_lists_participants_and_waiting_list(self, agenda_item, client, event):
        session = agenda_item.session
        presenter = session.presenter
        presenter.discord_username = "gm-handle"
        presenter.save()
        confirmed = UserFactory(
            username="modal-confirmed",
            email="modal-confirmed@example.com",
            discord_username="player-handle",
        )
        SessionParticipation.objects.create(
            session=session, user=confirmed, status=SessionParticipationStatus.CONFIRMED
        )
        waiter = UserFactory(username="modal-waiter", email="modal-waiter@example.com")
        SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        response = client.get(_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=[
                "gm-handle",
                "player-handle",
                confirmed.full_name,
                "Enrolled (1/10)",
                "Waiting List",
                waiter.full_name,
            ],
        )

    def test_renders_unlimited_capacity_and_min_age(
        self, active_user, client, event, space
    ):
        session = SessionFactory(
            event=event,
            category=None,
            presenter=active_user,
            display_name=active_user.full_name,
            participants_limit=0,
            min_age=18,
        )
        AgendaItemFactory(session=session, space=space)
        SessionParticipation.objects.create(
            session=session,
            user=UserFactory(
                username="modal-unlimited", email="modal-unlimited@example.com"
            ),
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = client.get(_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["Enrolled (1)", "Minimum Age", "18+"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_authenticated_viewer_sees_enroll_actions(
        self, authenticated_client, agenda_item, event
    ):
        response = authenticated_client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["with others"],
            not_contains=["Login to Enroll", "Enroll Anonymously"],
        )

    def test_renders_session_without_presenter(self, client, event, space):
        session = SessionFactory(
            event=event,
            category=None,
            presenter=None,
            display_name="Mystery Host",
            participants_limit=10,
            min_age=0,
        )
        AgendaItemFactory(session=session, space=space)

        response = client.get(_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["Mystery Host"],
        )

    def test_viewer_enrolled_shows_status(
        self, authenticated_client, active_user, agenda_item, event
    ):
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=active_user,
            status=SessionParticipationStatus.CONFIRMED,
        )

        response = authenticated_client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["You are enrolled in this session"],
        )

    def test_viewer_on_waiting_list_shows_status(
        self, authenticated_client, active_user, agenda_item, event
    ):
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=active_user,
            status=SessionParticipationStatus.WAITING,
        )

        response = authenticated_client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["You are on the waiting list"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_anonymous_viewer_sees_enroll_button(
        self, agenda_item, anonymous_user_factory, client, event, settings, sphere
    ):
        user = anonymous_user_factory()
        _activate_anonymous(
            client,
            sphere=sphere,
            event=event,
            code=user.slug.split("_")[1],
            settings=settings,
        )

        response = client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["Enroll Anonymously"],
        )

    @pytest.mark.usefixtures("enrollment_config")
    def test_anonymous_enrolled_viewer_sees_manage_link(
        self, agenda_item, anonymous_user_factory, client, event, settings, sphere
    ):
        user = anonymous_user_factory()
        SessionParticipation.objects.create(
            session=agenda_item.session,
            user=user,
            status=SessionParticipationStatus.CONFIRMED,
        )
        _activate_anonymous(
            client,
            sphere=sphere,
            event=event,
            code=user.slug.split("_")[1],
            settings=settings,
        )

        response = client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=["Manage Enrollment"],
        )

    def test_anonymous_viewer_unknown_code_renders(
        self, agenda_item, client, event, settings, sphere
    ):
        _activate_anonymous(
            client, sphere=sphere, event=event, code="9999", settings=settings
        )

        response = client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=f'id="session-{agenda_item.session.pk}"',
        )

    def test_anonymous_viewer_wrong_site_renders(
        self, agenda_item, anonymous_user_factory, client, event, settings, sphere
    ):
        user = anonymous_user_factory()
        _activate_anonymous(
            client,
            sphere=sphere,
            event=event,
            code=user.slug.split("_")[1],
            settings=settings,
            site_id=sphere.site.id + 9999,
        )

        response = client.get(_url(event, agenda_item.session.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=_TEMPLATE,
            context_data=ANY,
            contains=f'id="session-{agenda_item.session.pk}"',
        )
