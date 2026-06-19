"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/delete."""

from datetime import UTC, datetime, timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    AgendaItem,
    ProposalCategory,
    Session,
    SessionParticipation,
)
from tests.integration.conftest import (
    AreaFactory,
    EventFactory,
    SpaceFactory,
    UserFactory,
    VenueFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _make_session(event, sphere, **kwargs):
    category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
    defaults = {
        "category": category,
        "presenter": None,
        "display_name": "Test Host",
        "title": "Test Session",
        "slug": "test-session",
        "sphere": sphere,
        "participants_limit": 5,
        "status": "pending",
    }
    defaults.update(kwargs)
    return Session.objects.create(**defaults)


def _schedule(session, event):
    space = SpaceFactory(area=AreaFactory(venue=VenueFactory(event=event)))
    start = datetime.now(UTC) + timedelta(days=7)
    session.status = "scheduled"
    session.save(update_fields=["status"])
    return AgendaItem.objects.create(
        session=session,
        space=space,
        start_time=start,
        end_time=start + timedelta(hours=2),
    )


class TestProposalDeleteActionView:
    @staticmethod
    def get_url(event, proposal_id):
        return reverse(
            "panel:proposal-delete",
            kwargs={"slug": event.slug, "proposal_id": proposal_id},
        )

    def test_post_redirects_anonymous_user_to_login(self, client, event, sphere):
        session = _make_session(event, sphere)
        url = self.get_url(event, session.pk)

        response = client.post(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )
        session.refresh_from_db()
        assert session.deleted_at is None

    def test_post_redirects_non_manager_user(self, authenticated_client, event, sphere):
        session = _make_session(event, sphere)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )
        session.refresh_from_db()
        assert session.deleted_at is None

    def test_post_soft_deletes_session_and_redirects(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, sphere)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session deleted.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        assert not Session.objects.filter(pk=session.pk).exists()
        dead = Session.all_objects.get(pk=session.pk)
        assert dead.deleted_at is not None

    def test_post_frees_timetable_slot_and_retains_participations(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, sphere)
        agenda_item = _schedule(session, event)
        participation = SessionParticipation.objects.create(
            session=session,
            user=UserFactory(username="enrollee", email="enrollee@example.com"),
            status="confirmed",
        )

        authenticated_client.post(self.get_url(event, session.pk))

        assert not AgendaItem.objects.filter(pk=agenda_item.pk).exists()
        assert SessionParticipation.objects.filter(pk=participation.pk).exists()

    def test_post_excludes_soft_deleted_from_listing(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        session = _make_session(event, sphere)

        authenticated_client.post(self.get_url(event, session.pk))

        response = authenticated_client.get(
            reverse("panel:proposals", kwargs={"slug": event.slug})
        )
        assert session.title not in response.content.decode()

    def test_post_redirects_when_proposal_not_found(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        url = self.get_url(event, 99999)

        response = authenticated_client.post(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        session = _make_session(other_event, sphere)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Proposal not found.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        session.refresh_from_db()
        assert session.deleted_at is None
