from datetime import UTC, datetime, timedelta
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
    make_timetable_session,
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
                        acknowledged_by_name=None,
                    )
                ],
                "pending_count": 1,
            },
        )

    def test_an_announced_removal_shows_who_announced_it(
        self, panel_client, event, active_user, session, room
    ):
        log = _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.UNASSIGN,
            old_space=room,
            old_start_time=_WHEN,
            acknowledged_by=active_user,
            acknowledgement_time=_WHEN,
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
                        kind=ErratumKind.REMOVED,
                        session_id=session.pk,
                        session_title=session.title,
                        user_name=active_user.name,
                        creation_time=log.creation_time,
                        old_space_name="Room A",
                        old_start_time=_WHEN,
                        new_space_name=None,
                        new_start_time=None,
                        acknowledged_by_name=active_user.name,
                    )
                ],
                "pending_count": 0,
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
            moved_from=out,
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
                        acknowledged_by_name=None,
                    )
                ],
                "pending_count": 1,
            },
        )

    def test_a_move_made_on_the_timetable_shows_as_one_erratum(
        self, panel_client, event, active_user, room, proposal_category
    ):
        # Through the real assign endpoint: the move is recorded where it
        # happens, so the page never has to guess two rows back into one.
        destination = SpaceFactory(event=event, name="Room B")
        session = make_timetable_session(proposal_category, status="accepted")
        assign_url = reverse("panel:timetable-assign", kwargs={"slug": event.slug})
        for space in (room, destination):
            panel_client.post(
                assign_url,
                data={
                    "session_pk": session.pk,
                    "space_pk": space.pk,
                    "start_time": event.start_time.isoformat(),
                    "end_time": (event.start_time + timedelta(hours=1)).isoformat(),
                },
            )
        # The endpoint stamps the rows, so the times come back off them.
        first, out, into = ScheduleChangeLog.objects.order_by("pk")

        response = panel_client.get(self._url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/errata.html",
            context_data={
                **panel_context(
                    event,
                    active_nav="errata",
                    hosts_count=1,
                    rooms_count=2,
                    scheduled_sessions=1,
                    total_sessions=1,
                    total_proposals=1,
                ),
                "errata": [
                    ErratumDTO(
                        log_pks=[out.pk, into.pk],
                        kind=ErratumKind.MOVED,
                        session_id=session.pk,
                        session_title=session.title,
                        user_name=active_user.name,
                        creation_time=into.creation_time,
                        old_space_name="Room A",
                        old_start_time=event.start_time,
                        new_space_name="Room B",
                        new_start_time=event.start_time,
                        acknowledged_by_name=None,
                    ),
                    ErratumDTO(
                        log_pks=[first.pk],
                        kind=ErratumKind.ADDED,
                        session_id=session.pk,
                        session_title=session.title,
                        user_name=active_user.name,
                        creation_time=first.creation_time,
                        old_space_name=None,
                        old_start_time=None,
                        new_space_name="Room A",
                        new_start_time=event.start_time,
                        acknowledged_by_name=None,
                    ),
                ],
                "pending_count": 2,
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

    def test_unknown_event_reports_not_found(self, panel_client, pending):
        response = panel_client.post(
            reverse("panel:erratum-acknowledge", kwargs={"slug": "nope"}),
            data={"log_pk": [pending.pk], "acknowledged": "1"},
        )

        assert_event_not_found(response)
        pending.refresh_from_db()
        assert pending.acknowledgement_time is None

    def test_a_request_naming_no_row_is_refused(self, panel_client, event, pending):
        response = panel_client.post(self._url(event), data={"acknowledged": "1"})

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        pending.refresh_from_db()
        assert pending.acknowledgement_time is None

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
            moved_from=out,
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

        response = panel_client.post(
            self._url(event), data={"log_pk": [foreign.pk], "acknowledged": "1"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        foreign.refresh_from_db()
        assert foreign.acknowledgement_time is None

    # "²".isdigit() is True and int("²") raises, as does an int literal over
    # the 4300-digit limit, so neither may reach the service unguarded.
    @pytest.mark.parametrize("raw_pk", ("--5", "²", "1" * 4301))
    def test_a_malformed_pk_is_refused(self, panel_client, event, pending, raw_pk):
        response = panel_client.post(
            self._url(event), data={"log_pk": [raw_pk], "acknowledged": "1"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        pending.refresh_from_db()
        assert pending.acknowledgement_time is None

    def test_a_row_from_before_publication_is_refused(
        self, panel_client, sphere, active_user
    ):
        unpublished = EventFactory(sphere=sphere, publication_time=None)
        early = _log(
            unpublished,
            SessionFactory(event=unpublished),
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=SpaceFactory(event=unpublished),
            new_start_time=_WHEN,
        )

        response = panel_client.post(
            self._url(unpublished), data={"log_pk": [early.pk], "acknowledged": "1"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        early.refresh_from_db()
        assert early.acknowledgement_time is None

    def test_half_a_move_is_refused(
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
        _log(
            event,
            session,
            active_user,
            ScheduleChangeAction.ASSIGN,
            new_space=SpaceFactory(event=event, name="Room B"),
            new_start_time=_WHEN,
            moved_from=out,
        )

        response = panel_client.post(
            self._url(event), data={"log_pk": [out.pk], "acknowledged": "1"}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        assert not ScheduleChangeLog.objects.filter(
            acknowledgement_time__isnull=False
        ).exists()

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
