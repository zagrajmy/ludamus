from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from django.urls import reverse

from ludamus.links.db.django.models import ScheduleChangeLog, SphereMembership
from ludamus.pacts.errata import ErratumDTO, ErratumKind
from ludamus.pacts.legacy import ScheduleChangeAction
from ludamus.pacts.multiverse import SphereRole
from tests.integration.conftest import EventFactory, SessionFactory, SpaceFactory
from tests.integration.utils import assert_login_required, assert_response
from tests.integration.web.panel.helpers import (
    assert_event_not_found,
    assert_not_a_manager,
    panel_context,
)

_WHEN = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)


def _log(event, session, user, action, **kwargs):
    return ScheduleChangeLog.objects.create(
        event=event, session=session, user=user, action=action, **kwargs
    )


@pytest.fixture(name="session")
def session_fixture(event):
    return SessionFactory(event=event)


@pytest.fixture(name="room")
def room_fixture(event):
    return SpaceFactory(event=event, name="Room A")


@pytest.mark.django_db
class TestErrataPageView:
    @staticmethod
    def _url(event):
        return reverse("panel:errata", kwargs={"slug": event.slug})

    def test_anonymous_redirected_to_login(self, client, event):
        url = self._url(event)

        response = client.get(url)

        assert_login_required(response, url)

    def test_non_manager_redirected(self, authenticated_client, event):
        response = authenticated_client.get(self._url(event))

        assert_not_a_manager(response)

    def test_unknown_event_reports_not_found(self, panel_client):
        response = panel_client.get(reverse("panel:errata", kwargs={"slug": "nope"}))

        assert_event_not_found(response)

    def test_published_event_without_changes_is_empty(self, panel_client, event):
        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/errata.html",
            context_data={
                **panel_context(event, active_nav="errata"),
                "errata": [],
                "pending_count": 0,
            },
        )

    def test_unpublished_event_has_no_errata(self, panel_client, sphere, active_user):
        # The only event in the sphere, so the sidebar context stays a
        # one-element list.
        unpublished = EventFactory(sphere=sphere, publication_time=None)
        _log(
            unpublished,
            SessionFactory(event=unpublished),
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=SpaceFactory(event=unpublished),
            new_start_time=_WHEN,
        )

        response = panel_client.get(self._url(unpublished))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/errata.html",
            context_data={
                **panel_context(unpublished, active_nav="errata", rooms_count=1),
                "errata": [],
                "pending_count": 0,
            },
        )

    def test_an_assignment_shows_as_an_added_erratum(
        self, panel_client, event, active_user, session, room
    ):
        log = _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=room,
            new_start_time=_WHEN,
        )

        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/errata.html",
            context_data={
                **panel_context(event, active_nav="errata", rooms_count=1),
                "errata": [
                    ErratumDTO(
                        log_pks=[log.pk],
                        kind=ErratumKind.ADDED,
                        session_id=session.pk,
                        session_title=session.title,
                        user_name=active_user.name,
                        creation_time=log.creation_time,
                        old_space_name=None,
                        old_start_time=None,
                        new_space_name="Room A",
                        new_start_time=_WHEN,
                        is_acknowledged=False,
                        acknowledged_by_name="",
                    )
                ],
                "pending_count": 1,
            },
        )

    def test_the_two_rows_of_a_move_show_as_one_erratum(
        self, panel_client, event, active_user, session, room
    ):
        destination = SpaceFactory(event=event, name="Room B")
        out = _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.UNASSIGN,
            old_space=room,
            old_start_time=_WHEN,
        )
        into = _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=destination,
            new_start_time=_WHEN,
        )

        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/errata.html",
            context_data={
                **panel_context(event, active_nav="errata", rooms_count=2),
                "errata": [
                    ErratumDTO(
                        log_pks=[out.pk, into.pk],
                        kind=ErratumKind.MOVED,
                        session_id=session.pk,
                        session_title=session.title,
                        user_name=active_user.name,
                        creation_time=into.creation_time,
                        old_space_name="Room A",
                        old_start_time=_WHEN,
                        new_space_name="Room B",
                        new_start_time=_WHEN,
                        is_acknowledged=False,
                        acknowledged_by_name="",
                    )
                ],
                "pending_count": 1,
            },
        )


@pytest.mark.django_db
class TestErratumAcknowledgeActionView:
    @staticmethod
    def _url(event):
        return reverse("panel:erratum-acknowledge", kwargs={"slug": event.slug})

    @pytest.fixture(name="pending")
    def pending_fixture(self, event, session, room, active_user):
        return _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=room,
            new_start_time=_WHEN,
        )

    def test_manager_marks_a_change_announced(
        self, panel_client, event, pending, active_user
    ):
        response = panel_client.post(
            self._url(event), data={"log_pk": [pending.pk], "acknowledged": "1"}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("panel:errata", kwargs={"slug": event.slug}),
        )
        pending.refresh_from_db()
        assert pending.acknowledged_by == active_user
        assert pending.acknowledgement_time is not None

    def test_both_rows_of_a_move_are_marked_together(
        self, panel_client, event, session, room, active_user
    ):
        out = _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.UNASSIGN,
            old_space=room,
            old_start_time=_WHEN,
        )
        into = _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=SpaceFactory(event=event, name="Room B"),
            new_start_time=_WHEN,
        )

        panel_client.post(
            self._url(event), data={"log_pk": [out.pk, into.pk], "acknowledged": "1"}
        )

        assert not ScheduleChangeLog.objects.filter(
            acknowledgement_time__isnull=True
        ).exists()

    def test_an_announcement_can_be_taken_back(
        self, panel_client, event, pending, active_user
    ):
        pending.acknowledged_by = active_user
        pending.acknowledgement_time = _WHEN
        pending.save()

        panel_client.post(
            self._url(event), data={"log_pk": [pending.pk], "acknowledged": "0"}
        )

        pending.refresh_from_db()
        assert pending.acknowledged_by is None
        assert pending.acknowledgement_time is None

    def test_a_log_row_of_another_event_is_untouched(
        self, panel_client, event, sphere, active_user
    ):
        other = EventFactory(sphere=sphere)
        foreign = _log(
            other,
            SessionFactory(event=other),
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=SpaceFactory(event=other),
            new_start_time=_WHEN,
        )

        panel_client.post(
            self._url(event), data={"log_pk": [foreign.pk], "acknowledged": "1"}
        )

        foreign.refresh_from_db()
        assert foreign.acknowledgement_time is None

    def test_a_comms_member_may_mark_a_change_announced(
        self, authenticated_client, sphere, active_user, event, pending
    ):
        SphereMembership.objects.create(
            sphere=sphere, user=active_user, role=SphereRole.COMMS
        )

        authenticated_client.post(
            self._url(event), data={"log_pk": [pending.pk], "acknowledged": "1"}
        )

        pending.refresh_from_db()
        assert pending.acknowledgement_time is not None

    def test_a_stranger_may_not(self, authenticated_client, event, pending):
        response = authenticated_client.post(
            self._url(event), data={"log_pk": [pending.pk], "acknowledged": "1"}
        )

        assert_not_a_manager(response)
        pending.refresh_from_db()
        assert pending.acknowledgement_time is None
