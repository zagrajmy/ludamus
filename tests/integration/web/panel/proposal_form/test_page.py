"""Access, rendering and saving of the proposal form page."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DataError
from django.urls import reverse
from django.utils.http import urlencode

from ludamus.gates.web.django.forms import MAX_STORED_PARTICIPANTS_LIMIT
from ludamus.links.db.django.models import (
    Facilitator,
    Notification,
    ProposalCategory,
    Session,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.links.db.django.repositories.sessions import SessionRepository
from ludamus.pacts.legacy import EventDTO, NotificationKind
from tests.integration.conftest import (
    PNG_BYTES,
    AgendaItemFactory,
    EventFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import (
    FormErrorsMatcher,
    assert_login_required,
    assert_response,
)
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    assert_proposal_not_found,
    facilitator_list_item_dto,
)
from tests.integration.web.panel.proposal_form.helpers import (
    assert_created,
    form_cancel_url,
    form_context,
    form_page,
    form_url,
    make_session,
)

DEFAULT_SESSION_PARTICIPANTS = 5
OVER_COLUMN_WIDTH = MAX_STORED_PARTICIPANTS_LIMIT + 1
MISSING_EVENT_ROUTES = (
    pytest.param("panel:proposal-create", {"slug": "nonexistent"}, id="create"),
    pytest.param(
        "panel:proposal-edit", {"slug": "nonexistent", "proposal_id": 1}, id="edit"
    ),
)


class TestBothModes:
    def test_get_redirects_anonymous_user_to_login(self, client, form_mode):
        response = client.get(form_mode.url)

        assert_login_required(response, form_mode.url)

    def test_post_redirects_anonymous_user_to_login(self, client, form_mode):
        response = client.post(
            form_mode.url, data={"title": "New Title", "facilitator_name": "Host"}
        )

        assert_login_required(response, form_mode.url)

    def test_get_redirects_non_manager_user(self, authenticated_client, form_mode):
        response = authenticated_client.get(form_mode.url)

        assert_not_a_manager(response)

    def test_post_redirects_non_manager_user(self, authenticated_client, form_mode):
        response = authenticated_client.post(
            form_mode.url, data={"title": "New Title", "facilitator_name": "Host"}
        )

        assert_not_a_manager(response)

    @pytest.mark.parametrize(("route", "kwargs"), MISSING_EVENT_ROUTES)
    def test_get_redirects_when_event_not_found(self, panel_client, route, kwargs):
        response = panel_client.get(reverse(route, kwargs=kwargs))

        assert_event_not_found(response)

    @pytest.mark.parametrize(("route", "kwargs"), MISSING_EVENT_ROUTES)
    def test_post_redirects_when_event_not_found(self, panel_client, route, kwargs):
        response = panel_client.post(reverse(route, kwargs=kwargs), data={})

        assert_event_not_found(response)

    def test_get_ok_for_sphere_manager(self, panel_client, event, form_mode):
        response = panel_client.get(form_mode.url)

        assert_response(response, HTTPStatus.OK, **form_page(event, form_mode.session))

    def test_post_shows_errors_on_invalid_data(self, panel_client, event, form_mode):
        response = panel_client.post(
            form_mode.url, data={"category_id": "", "title": "", "facilitator_name": ""}
        )

        # An empty category_id falls back to a category, so the form still
        # renders that category's fields alongside the error.
        assert_response(response, HTTPStatus.OK, **form_page(event, form_mode.session))
        assert response.context["form"].errors


class TestCreate:
    def test_post_creates_session_with_unique_slug_on_collision(
        self, panel_client, event
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        Session.objects.create(
            event=event,
            category=category,
            presenter=None,
            facilitator_name="Host",
            title="Existing Session",
            slug="my-new-session",
            participants_limit=0,
            status="pending",
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "My New Session",
                "facilitator_name": "Test Host",
                "description": "",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = assert_created(response, event, title="My New Session")
        assert new_session.slug != "my-new-session"

    def test_post_transliterates_a_polish_title_into_the_slug(
        self, panel_client, event
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Łódzkie Łowy",
                "facilitator_name": "Test Host",
                "description": "",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
            },
        )

        new_session = assert_created(response, event, title="Łódzkie Łowy")
        assert new_session.slug == "lodzkie-lowy"

    def test_post_creates_session_with_cover_image(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Session With Cover",
                "facilitator_name": "Test Host",
                "description": "",
                "contact_email": "",
                "participants_limit": "",
                "min_age": "",
                "duration": "",
                "cover_image": SimpleUploadedFile(
                    "cover.png", PNG_BYTES, content_type="image/png"
                ),
            },
        )

        new_session = Session.objects.get(title="Session With Cover")
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal created successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": new_session.pk},
            ),
        )
        assert new_session.cover_image

    @pytest.mark.postgres
    def test_post_second_same_title_session_saves(self, panel_client, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )
        slug_max_length = 50
        submissions = 2
        title = "Midnight Heist One-Shot Adventure For New Players"
        data = {
            "facilitators_submitted": "1",
            "facilitator_ids": [facilitator.pk],
            "category_id": category.pk,
            "title": title,
            "facilitator_name": "Test Host",
        }

        for _ in range(submissions):
            panel_client.post(form_url(event), data=data)

        sessions = Session.objects.filter(title=title)
        assert sessions.count() == submissions
        assert all(len(session.slug) <= slug_max_length for session in sessions)

    def test_post_surfaces_db_error_as_form_error(
        self, panel_client, event, monkeypatch
    ):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        facilitator = Facilitator.objects.create(
            event=event, display_name="Alice", slug="alice", user=None
        )

        def _raise(*_args, **_kwargs):
            raise DataError("value too long for type character varying(50)")

        monkeypatch.setattr(SessionRepository, "create", _raise)

        response = panel_client.post(
            form_url(event),
            data={
                "facilitators_submitted": "1",
                "facilitator_ids": [facilitator.pk],
                "category_id": category.pk,
                "title": "Boom",
                "facilitator_name": "Test Host",
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event),
                "all_facilitators": [facilitator_list_item_dto(facilitator)],
                "assigned_facilitator_pks": {facilitator.pk},
            },
            messages=[
                (
                    messages.ERROR,
                    "Couldn't save the session. Please check your input and try again.",
                )
            ],
        )
        assert not Session.objects.filter(title="Boom").exists()


class TestEdit:
    def test_get_points_cancel_back_through_the_filtered_list(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = make_session(event)
        back = f"{reverse('panel:proposals', kwargs={'slug': event.slug})}?status=all"
        expected = form_page(event, session)
        expected["context_data"][
            "cancel_url"
        ] = f"{form_cancel_url(event, session.pk)}?{urlencode({'next': back})}"

        response = authenticated_client.get(
            f"{form_url(event, session.pk)}?{urlencode({'next': back})}"
        )

        assert_response(response, HTTPStatus.OK, **expected)

    def test_get_redirects_when_proposal_not_found(self, panel_client, event):
        response = panel_client.get(form_url(event, 99999))

        assert_proposal_not_found(response, event)

    def test_get_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = make_session(other_event)
        url = form_url(event, session.pk)

        response = panel_client.get(url)

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_not_found(self, panel_client, event):
        response = panel_client.post(form_url(event, 99999), data={})

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = make_session(other_event)
        title = session.title

        response = panel_client.post(
            form_url(event, session.pk),
            data={"title": "Updated", "facilitator_name": "Host"},
        )

        assert_proposal_not_found(response, event)
        session.refresh_from_db()
        assert session.title == title

    def test_post_updates_session_and_redirects(self, panel_client, event):
        session = make_session(event)

        new_limit = 10
        new_min_age = 18
        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "facilitator_name": "New Host",
                "description": "Updated description",
                "contact_email": "",
                "participants_limit": new_limit,
                "min_age": new_min_age,
                "duration_hours": 2,
                "duration_minutes": 30,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.title == "Updated Title"
        assert session.facilitator_name == "New Host"
        assert session.description == "Updated description"
        assert session.participants_limit == new_limit
        assert session.min_age == new_min_age
        assert session.duration == "PT2H30M"

    @pytest.mark.parametrize(
        ("contact_email", "contact_language"),
        (("host@example.com", "pl"), ("other@example.com", "")),
        ids=("kept", "replaced"),
    )
    def test_post_keeps_the_contact_language_only_with_its_address(
        self, panel_client, event, contact_email, contact_language
    ):
        session = make_session(event, contact_language="pl")

        panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": session.title,
                "facilitator_name": session.facilitator_name,
                "description": session.description,
                "contact_email": contact_email,
                "participants_limit": session.participants_limit,
                "min_age": 0,
                "duration_hours": 2,
                "duration_minutes": 0,
            },
        )

        session.refresh_from_db()
        assert (session.contact_email, session.contact_language) == (
            contact_email,
            contact_language,
        )

    def test_post_carries_the_list_filters_back_to_the_detail_page(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = make_session(event)
        back = f"{reverse('panel:proposals', kwargs={'slug': event.slug})}?status=all"

        response = authenticated_client.post(
            f"{form_url(event, session.pk)}?{urlencode({'next': back})}",
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "facilitator_name": "New Host",
                "description": "Updated description",
                "contact_email": "",
                "participants_limit": 10,
                "min_age": 18,
                "duration_hours": 2,
                "duration_minutes": 30,
            },
        )

        detail_url = reverse(
            "panel:proposal-detail",
            kwargs={"slug": event.slug, "proposal_id": session.pk},
        )
        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=f"{detail_url}?{urlencode({'next': back})}",
        )

    def test_post_ignores_an_offsite_next(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = make_session(event)

        response = authenticated_client.post(
            f"{form_url(event, session.pk)}"
            f"?{urlencode({'next': 'https://evil.example.com/'})}",
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "facilitator_name": "New Host",
                "description": "Updated description",
                "contact_email": "",
                "participants_limit": 10,
                "min_age": 18,
                "duration_hours": 2,
                "duration_minutes": 30,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )

    def test_post_surfaces_db_error_as_form_error(
        self, panel_client, event, monkeypatch
    ):
        session = make_session(event)

        def _raise(*_args, **_kwargs):
            raise DataError("value too long for type character varying(50)")

        monkeypatch.setattr(SessionRepository, "update", _raise)
        error = "Couldn't save your changes. Please check your input and try again."

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "facilitator_name": "New Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={**form_context(event, session)},
            messages=[(messages.ERROR, error)],
        )
        session.refresh_from_db()
        assert session.title == "Test Session"

    def test_post_reassigns_category(self, panel_client, event):
        session = make_session(event)
        new_category = ProposalCategory.objects.create(
            event=event, name="Board games", slug="board-games"
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": new_category.pk,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.category_id == new_category.pk

    def test_post_ignores_category_from_other_event(self, panel_client, sphere, event):
        session = make_session(event)
        original_category_id = session.category_id
        other_event = EventFactory(
            sphere=sphere, start_time=event.start_time + timedelta(days=1)
        )
        foreign_category = ProposalCategory.objects.create(
            event=other_event, name="Foreign", slug="foreign"
        )

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": foreign_category.pk,
                "title": "Test Session",
                "facilitator_name": "Test Host",
                "participants_limit": 5,
                "min_age": 0,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "events": [
                    EventDTO.model_validate(other_event),
                    EventDTO.model_validate(event),
                ],
            },
        )
        assert response.context["form"].errors
        session.refresh_from_db()
        assert session.category_id == original_category_id

    def test_post_uploads_cover_image(self, panel_client, event):
        session = make_session(event)
        image = SimpleUploadedFile("cover.png", PNG_BYTES, content_type="image/png")

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated Title",
                "facilitator_name": "New Host",
                "cover_image": image,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.cover_image
        assert session.cover_image_url.startswith("/media/sessions/")

    def test_post_clears_cover_image(
        self, panel_client, event, django_capture_on_commit_callbacks
    ):
        session = make_session(event)
        session.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        session.save()
        storage = session.cover_image.storage
        old_name = session.cover_image.name

        with django_capture_on_commit_callbacks(execute=True):
            response = panel_client.post(
                form_url(event, session.pk),
                data={
                    "category_id": session.category_id,
                    "title": "Updated Title",
                    "facilitator_name": "New Host",
                    "cover_image-clear": "on",
                },
            )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert not session.cover_image
        assert not storage.exists(old_name)

    def test_post_rejects_a_limit_wider_than_the_column(self, panel_client, event):
        # Unbounded is not unlimited: Postgres integer stops at 2**31-1. The
        # field says so itself, rather than leaving the panel to fall back on
        # its generic "couldn't save" message.
        session = make_session(event, participants_limit=DEFAULT_SESSION_PARTICIPANTS)

        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "description": "d",
                "contact_email": "",
                "participants_limit": OVER_COLUMN_WIDTH,
                "min_age": 0,
                "duration_hours": 2,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/proposal-form.html",
            context_data={
                **form_context(event, session),
                "form": FormErrorsMatcher(
                    participants_limit=["Enter a smaller number."]
                ),
            },
        )
        session.refresh_from_db()
        assert session.participants_limit == DEFAULT_SESSION_PARTICIPANTS

    @pytest.mark.usefixtures("enrollment_config")
    def test_post_raising_capacity_promotes_waiter(self, panel_client, event, waiter):
        session = make_session(event, participants_limit=1)
        space = SpaceFactory(event=event)
        AgendaItemFactory(session=session, space=space)
        filler = UserFactory(username="filler", email="filler@example.com")
        SessionParticipation.objects.create(
            session=session, user=filler, status=SessionParticipationStatus.CONFIRMED
        )
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )

        raised_limit = 2
        response = panel_client.post(
            form_url(event, session.pk),
            data={
                "category_id": session.category_id,
                "title": "Updated",
                "facilitator_name": "Host",
                "description": "d",
                "contact_email": "",
                "participants_limit": raised_limit,
                "min_age": 0,
                "duration_hours": 2,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Proposal updated successfully.")],
            url=reverse(
                "panel:proposal-detail",
                kwargs={"slug": event.slug, "proposal_id": session.pk},
            ),
        )
        session.refresh_from_db()
        assert session.participants_limit == raised_limit
        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()
