"""Integration tests for /panel/event/<slug>/proposals/<proposal_id>/do/delete."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.db import connection
from django.test import Client
from django.urls import reverse

from ludamus.links.db.django.models import (
    AgendaItem,
    ScheduleChangeLog,
    Session,
    SessionParticipation,
)
from ludamus.pacts import ScheduleChangeAction
from tests.integration.conftest import EventFactory, SpaceFactory, UserFactory
from tests.integration.utils import assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_login_required,
    assert_not_a_manager,
    assert_proposal_not_found,
    make_proposal,
)


def _schedule(session, event):
    space = SpaceFactory(event=event)
    start = datetime.now(UTC) + timedelta(days=7)
    session.status = "accepted"
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

    def test_post_redirects_anonymous_user_to_login(self, client, event):
        session = make_proposal(event)
        url = self.get_url(event, session.pk)

        response = client.post(url)

        assert_login_required(response, url)
        session.refresh_from_db()
        assert session.deleted_at is None

    def test_post_redirects_non_manager_user(self, authenticated_client, event):
        session = make_proposal(event)

        response = authenticated_client.post(self.get_url(event, session.pk))

        assert_not_a_manager(response)
        session.refresh_from_db()
        assert session.deleted_at is None

    def test_post_soft_deletes_session_and_redirects(self, panel_client, event):
        session = make_proposal(event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Session deleted.")],
            url=reverse("panel:proposals", kwargs={"slug": event.slug}),
        )
        assert not Session.objects.filter(pk=session.pk).exists()
        dead = Session.all_objects.get(pk=session.pk)
        assert dead.deleted_at is not None
        assert not ScheduleChangeLog.objects.filter(session_id=session.pk).exists()

    def test_post_frees_timetable_slot_and_retains_participations(
        self, panel_client, active_user, event
    ):
        session = make_proposal(event)
        agenda_item = _schedule(session, event)
        participation = SessionParticipation.objects.create(
            session=session,
            user=UserFactory(username="enrollee", email="enrollee@example.com"),
            status="confirmed",
        )

        panel_client.post(self.get_url(event, session.pk))

        assert not AgendaItem.objects.filter(pk=agenda_item.pk).exists()
        assert SessionParticipation.objects.filter(pk=participation.pk).exists()
        log = ScheduleChangeLog.objects.get(session_id=session.pk)
        assert log.action == ScheduleChangeAction.UNASSIGN
        assert log.user_id == active_user.pk

    @pytest.mark.postgres
    @pytest.mark.django_db(transaction=True)
    def test_concurrent_delete_frees_slot_exactly_once(
        self, active_user, sphere, event
    ):
        # Two managers delete the same scheduled session at once. The row lock
        # serializes them: the slot is freed once, so exactly one UNASSIGN log is
        # written. Without locking both requests would log the unassignment.
        sphere.managers.add(active_user)
        session = make_proposal(event)
        _schedule(session, event)
        url = self.get_url(event, session.pk)

        clients = []
        for _ in range(2):
            client = Client()
            client.force_login(active_user)
            clients.append(client)

        barrier = threading.Barrier(len(clients))

        def delete(client):
            barrier.wait()
            try:
                return client.post(url)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=len(clients)) as pool:
            responses = [
                future.result()
                for future in [pool.submit(delete, client) for client in clients]
            ]

        assert all(r.status_code == HTTPStatus.FOUND for r in responses)
        assert Session.all_objects.get(pk=session.pk).deleted_at is not None
        assert (
            ScheduleChangeLog.objects.filter(
                session_id=session.pk, action=ScheduleChangeAction.UNASSIGN
            ).count()
            == 1
        )

    def test_post_excludes_soft_deleted_from_listing(self, panel_client, event):
        session = make_proposal(event)

        panel_client.post(self.get_url(event, session.pk))

        response = panel_client.get(
            reverse("panel:proposals", kwargs={"slug": event.slug})
        )
        assert session.pk not in {
            proposal.pk for proposal in response.context["proposals"]
        }
        assert session.pk in {
            proposal.pk for proposal in response.context["deleted_proposals"]
        }

    def test_post_redirects_when_proposal_not_found(self, panel_client, event):
        url = self.get_url(event, 99999)

        response = panel_client.post(url)

        assert_proposal_not_found(response, event)

    def test_post_redirects_when_proposal_belongs_to_different_event(
        self, panel_client, sphere, event
    ):
        other_event = EventFactory(sphere=sphere)
        session = make_proposal(other_event)

        response = panel_client.post(self.get_url(event, session.pk))

        assert_proposal_not_found(response, event)
        session.refresh_from_db()
        assert session.deleted_at is None

    def test_post_redirects_when_event_not_found(self, panel_client):
        url = reverse(
            "panel:proposal-delete", kwargs={"slug": "no-such-event", "proposal_id": 1}
        )

        response = panel_client.post(url)

        assert_event_not_found(response)
