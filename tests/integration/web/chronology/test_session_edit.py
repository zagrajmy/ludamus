from http import HTTPStatus
from unittest.mock import ANY, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    Session,
    SessionField,
    SessionFieldOption,
    SessionFieldValue,
)
from ludamus.mills.chronology import SessionEditNotAllowedError, SessionSelfEditService
from ludamus.pacts import SessionDTO
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404

FRAGMENT = "chronology/parts/session-edit-form.html"
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _expected_session(session):
    session.refresh_from_db()
    return SessionDTO.model_validate(session)


@pytest.fixture(name="owned_session")
def owned_session_fixture(event, active_user, sphere):
    category = ProposalCategoryFactory(event=event)
    return SessionFactory(
        category=category,
        presenter=active_user,
        display_name=active_user.name,
        sphere=sphere,
        participants_limit=10,
        min_age=0,
        status="scheduled",
    )


def _url(event, session):
    return reverse(
        "web:chronology:session-edit",
        kwargs={"event_slug": event.slug, "session_id": session.pk},
    )


class TestSessionEditViewGet:
    def test_owner_gets_form_fragment(self, authenticated_client, event, owned_session):
        url = _url(event, owned_session)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=FRAGMENT,
            context_data={
                "session": _expected_session(owned_session),
                "form": ANY,
                "session_fields": [],
                "post_url": url,
                "saved": False,
            },
        )

    def test_anonymous_redirected_to_login(self, client, event, owned_session):
        url = _url(event, owned_session)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_non_owner_404(self, authenticated_client, event, sphere):
        category = ProposalCategoryFactory(event=event)
        other = UserFactory(username="other", email="other@example.com")
        session = SessionFactory(
            category=category, presenter=other, sphere=sphere, status="scheduled"
        )

        response = authenticated_client.get(_url(event, session))

        assert_response_404(response)

    def test_event_override_false_404(self, authenticated_client, event, owned_session):
        event.allow_facilitator_session_edit = False
        event.save()

        response = authenticated_client.get(_url(event, owned_session))

        assert_response_404(response)

    def test_wrong_event_slug_404(
        self, authenticated_client, sphere, owned_session, faker
    ):
        other_event = EventFactory(sphere=sphere, slug=faker.slug())
        url = reverse(
            "web:chronology:session-edit",
            kwargs={"event_slug": other_event.slug, "session_id": owned_session.pk},
        )

        response = authenticated_client.get(url)

        assert_response_404(response)

    def test_sphere_default_false_no_override_404(
        self, authenticated_client, event, owned_session, sphere
    ):
        sphere.allow_facilitator_session_edit = False
        sphere.save()

        response = authenticated_client.get(_url(event, owned_session))

        assert_response_404(response)

    def test_event_override_true_beats_sphere_false(
        self, authenticated_client, event, owned_session, sphere
    ):
        sphere.allow_facilitator_session_edit = False
        sphere.save()
        event.allow_facilitator_session_edit = True
        event.save()
        url = _url(event, owned_session)

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=FRAGMENT,
            context_data={
                "session": _expected_session(owned_session),
                "form": ANY,
                "session_fields": [],
                "post_url": url,
                "saved": False,
            },
        )


class TestSessionEditViewPost:
    @staticmethod
    def _data(**overrides):
        data = {"title": "Updated title", "display_name": "Updated name"}
        data.update(overrides)
        return data

    def test_htmx_post_saves_and_returns_saved_fragment(
        self, authenticated_client, event, owned_session
    ):
        url = _url(event, owned_session)

        response = authenticated_client.post(
            url, data=self._data(), headers={"hx-request": "true"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=FRAGMENT,
            context_data={
                "session": _expected_session(owned_session),
                "form": ANY,
                "session_fields": [],
                "post_url": url,
                "saved": True,
            },
        )
        owned_session.refresh_from_db()
        assert owned_session.title == "Updated title"
        assert owned_session.display_name == "Updated name"

    def test_post_uploads_cover_image(self, authenticated_client, event, owned_session):
        url = _url(event, owned_session)
        image = SimpleUploadedFile("cover.png", PNG_BYTES, content_type="image/png")

        response = authenticated_client.post(
            url, data=self._data(cover_image=image), headers={"hx-request": "true"}
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=FRAGMENT,
            context_data={
                "session": _expected_session(owned_session),
                "form": ANY,
                "session_fields": [],
                "post_url": url,
                "saved": True,
            },
        )
        owned_session.refresh_from_db()
        assert owned_session.cover_image
        assert owned_session.cover_image_url.startswith("/media/sessions/")

    def test_post_replacing_cover_deletes_previous_file(
        self, authenticated_client, event, owned_session
    ):
        owned_session.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        owned_session.save()
        storage = owned_session.cover_image.storage
        old_name = owned_session.cover_image.name
        new_image = SimpleUploadedFile("new.png", PNG_BYTES, content_type="image/png")

        authenticated_client.post(
            _url(event, owned_session),
            data=self._data(cover_image=new_image),
            headers={"hx-request": "true"},
        )

        owned_session.refresh_from_db()
        assert owned_session.cover_image.name != old_name
        assert not storage.exists(old_name)

    def test_post_clears_cover_image(self, authenticated_client, event, owned_session):
        owned_session.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        owned_session.save()
        storage = owned_session.cover_image.storage
        old_name = owned_session.cover_image.name

        authenticated_client.post(
            _url(event, owned_session),
            data=self._data(**{"cover_image-clear": "on"}),
            headers={"hx-request": "true"},
        )

        owned_session.refresh_from_db()
        assert not owned_session.cover_image
        assert not storage.exists(old_name)

    def test_non_htmx_post_saves_and_redirects(
        self, authenticated_client, event, owned_session
    ):
        response = authenticated_client.post(
            _url(event, owned_session), data=self._data()
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/chronology/event/{event.slug}/?session={owned_session.pk}",
        )
        owned_session.refresh_from_db()
        assert owned_session.title == "Updated title"

    def test_post_update_not_allowed_returns_404(
        self, authenticated_client, event, owned_session
    ):
        with patch.object(
            SessionSelfEditService, "update", side_effect=SessionEditNotAllowedError()
        ):
            response = authenticated_client.post(
                _url(event, owned_session),
                data=self._data(),
                headers={"hx-request": "true"},
            )

        assert_response_404(response)

    def test_invalid_post_returns_fragment_without_saving(
        self, authenticated_client, event, owned_session
    ):
        url = _url(event, owned_session)
        original = owned_session.title

        response = authenticated_client.post(
            url,
            data={"title": "", "display_name": "Name", "participants_limit": "-1"},
            headers={"hx-request": "true"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=FRAGMENT,
            context_data={
                "session": _expected_session(owned_session),
                "form": ANY,
                "session_fields": [],
                "post_url": url,
                "saved": False,
            },
        )
        owned_session.refresh_from_db()
        assert owned_session.title == original

    def test_invalid_post_keeps_existing_cover_preview(
        self, authenticated_client, event, owned_session
    ):
        owned_session.cover_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        owned_session.save()
        cover_url = owned_session.cover_image_url
        url = _url(event, owned_session)

        response = authenticated_client.post(
            url,
            data={"title": "", "display_name": "Name"},
            headers={"hx-request": "true"},
        )

        assert_response(
            response,
            HTTPStatus.OK,
            template_name=FRAGMENT,
            context_data={
                "session": _expected_session(owned_session),
                "form": ANY,
                "session_fields": [],
                "post_url": url,
                "saved": False,
            },
        )
        assert response.context["form"].fields["cover_image"].initial == cover_url
        assert cover_url.encode() in response.content

    def test_non_owner_404_no_write(self, authenticated_client, event, sphere):
        category = ProposalCategoryFactory(event=event)
        other = UserFactory(username="other", email="other@example.com")
        session = SessionFactory(
            category=category,
            presenter=other,
            sphere=sphere,
            title="Original",
            status="scheduled",
        )

        response = authenticated_client.post(
            _url(event, session), data=self._data(), headers={"hx-request": "true"}
        )

        assert_response_404(response)
        assert Session.objects.get(pk=session.pk).title == "Original"

    def test_opted_out_404_no_write(self, authenticated_client, event, owned_session):
        event.allow_facilitator_session_edit = False
        event.save()
        original = owned_session.title

        response = authenticated_client.post(
            _url(event, owned_session),
            data=self._data(),
            headers={"hx-request": "true"},
        )

        assert_response_404(response)
        owned_session.refresh_from_db()
        assert owned_session.title == original

    def test_htmx_post_replaces_existing_session_field_value(
        self, authenticated_client, event, owned_session
    ):
        field = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="text",
            order=0,
        )
        SessionFieldValue.objects.create(
            session=owned_session, field=field, value="D&D"
        )

        authenticated_client.post(
            _url(event, owned_session),
            data=self._data(session_field_system="Pathfinder"),
            headers={"hx-request": "true"},
        )

        values = SessionFieldValue.objects.filter(session=owned_session, field=field)
        assert values.count() == 1
        assert values.get().value == "Pathfinder"

    def _make_fields(self, event):
        genres = SessionField.objects.create(
            event=event,
            name="Genres",
            question="Which genres?",
            slug="genres",
            field_type="select",
            is_multiple=True,
            order=0,
        )
        SessionFieldOption.objects.create(
            field=genres, label="Horror", value="horror", order=0
        )
        SessionFieldOption.objects.create(
            field=genres, label="Comedy", value="comedy", order=1
        )
        system = SessionField.objects.create(
            event=event,
            name="System",
            question="Which system?",
            slug="system",
            field_type="select",
            allow_custom=True,
            order=1,
        )
        SessionFieldOption.objects.create(
            field=system, label="D&D", value="dnd", order=0
        )
        adult = SessionField.objects.create(
            event=event,
            name="18+",
            question="Adult?",
            slug="adult",
            field_type="checkbox",
            order=2,
        )
        notes = SessionField.objects.create(
            event=event,
            name="Notes",
            question="Notes?",
            slug="notes",
            field_type="text",
            allow_custom=True,
            max_length=99,
            order=3,
        )
        return genres, system, adult, notes

    def test_get_renders_every_field_type(
        self, authenticated_client, event, owned_session
    ):
        genres, system, adult, notes = self._make_fields(event)
        SessionFieldValue.objects.create(
            session=owned_session, field=genres, value=["horror"]
        )
        SessionFieldValue.objects.create(
            session=owned_session, field=system, value="dnd"
        )
        SessionFieldValue.objects.create(session=owned_session, field=adult, value=True)
        SessionFieldValue.objects.create(
            session=owned_session, field=notes, value="hello"
        )

        response = authenticated_client.get(_url(event, owned_session))

        assert response.status_code == HTTPStatus.OK
        content = response.content.decode()
        assert 'name="session_field_genres"' in content
        assert 'name="session_field_system_custom"' in content
        assert 'name="session_field_adult"' in content

    def test_htmx_post_saves_every_field_type(
        self, authenticated_client, event, owned_session
    ):
        genres, system, adult, notes = self._make_fields(event)

        authenticated_client.post(
            _url(event, owned_session),
            data=self._data(
                session_field_genres=["horror", "comedy"],
                session_field_system="",
                session_field_system_custom="Pathfinder",
                session_field_adult="true",
                session_field_notes="Some notes",
            ),
            headers={"hx-request": "true"},
        )

        get = SessionFieldValue.objects.get
        assert get(session=owned_session, field=genres).value == ["horror", "comedy"]
        assert get(session=owned_session, field=system).value == "Pathfinder"
        assert get(session=owned_session, field=adult).value is True
        assert get(session=owned_session, field=notes).value == "Some notes"
