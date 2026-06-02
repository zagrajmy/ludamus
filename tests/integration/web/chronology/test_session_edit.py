from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import Session
from tests.integration.conftest import (
    ProposalCategoryFactory,
    SessionFactory,
    UserFactory,
)
from tests.integration.utils import assert_response, assert_response_404


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


class TestSessionEditPageViewGet:
    def test_owner_gets_form(self, authenticated_client, event, owned_session):
        response = authenticated_client.get(_url(event, owned_session))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/session/edit.html",
            context_data={
                "event": ANY,
                "session": ANY,
                "form": ANY,
                "session_fields": [],
                "facilitators": [],
                "cancel_url": (
                    f"/chronology/event/{event.slug}/?session={owned_session.pk}"
                ),
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

        response = authenticated_client.get(_url(event, owned_session))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="chronology/session/edit.html",
            context_data={
                "event": ANY,
                "session": ANY,
                "form": ANY,
                "session_fields": [],
                "facilitators": [],
                "cancel_url": (
                    f"/chronology/event/{event.slug}/?session={owned_session.pk}"
                ),
            },
        )


class TestSessionEditPageViewPost:
    @staticmethod
    def _data(**overrides):
        data = {"title": "Updated title", "display_name": "Updated name"}
        data.update(overrides)
        return data

    def test_owner_updates_session(self, authenticated_client, event, owned_session):
        response = authenticated_client.post(
            _url(event, owned_session), data=self._data()
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session updated successfully.")],
            url=f"/chronology/event/{event.slug}/?session={owned_session.pk}",
        )
        owned_session.refresh_from_db()
        assert owned_session.title == "Updated title"
        assert owned_session.display_name == "Updated name"

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

        response = authenticated_client.post(_url(event, session), data=self._data())

        assert_response_404(response)
        assert Session.objects.get(pk=session.pk).title == "Original"

    def test_opted_out_404_no_write(self, authenticated_client, event, owned_session):
        event.allow_facilitator_session_edit = False
        event.save()
        original = owned_session.title

        response = authenticated_client.post(
            _url(event, owned_session), data=self._data()
        )

        assert_response_404(response)
        owned_session.refresh_from_db()
        assert owned_session.title == original
