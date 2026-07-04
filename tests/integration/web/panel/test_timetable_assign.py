from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import (
    AgendaItem,
    Notification,
    SessionParticipation,
    SessionParticipationStatus,
)
from ludamus.pacts.chronology import (
    TIMETABLE_SLOT_MINUTES,
    TIMETABLE_SNAP_MINUTES,
    TimetableGridDTO,
)
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import (
    AgendaItemFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    UserFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


def _empty_grid():
    return TimetableGridDTO(
        spaces=[],
        columns=[],
        groups=[],
        time_labels=[],
        total_minutes=0,
        event_start_iso="",
        slot_minutes=TIMETABLE_SLOT_MINUTES,
        snap_minutes=TIMETABLE_SNAP_MINUTES,
        page=1,
        total_pages=1,
        total_spaces=0,
        available_dates=[],
        selected_date=None,
    )


class TestTimetableGridPartView:
    """Tests for /panel/event/<slug>/timetable/parts/grid/ partial."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-grid-part", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.get(url)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-grid-part", kwargs={"slug": "nonexistent"})

        response = authenticated_client.get(url)

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_room_page_invalid_value_defaults_to_one(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(
            self.get_url(event), {"room_page": "not-a-number"}
        )

        assert response.status_code == HTTPStatus.OK

    def test_ok_returns_grid_partial(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.get(self.get_url(event))

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/parts/timetable-grid.html",
            context_data={
                "grid": _empty_grid(),
                "filter_track_pk": None,
                "conflict_session_pks": set(),
                "slot_violation_session_pks": set(),
                "slug": event.slug,
            },
        )


class TestTimetableAssignView:
    """Tests for /panel/event/<slug>/timetable/do/assign/ POST endpoint."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-assign", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, {})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), {})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, PERMISSION_ERROR)],
            url="/",
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-assign", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, {})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_returns_422_on_missing_params(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), {})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_assigns_session_and_returns_204(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.get("HX-Trigger") is not None
        session.refresh_from_db()
        assert session.status == "scheduled"
        assert session.agenda_item.session_confirmed is True

    def test_assign_leaves_unconfirmed_when_auto_confirm_off(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        event = EventFactory(sphere=sphere, auto_confirm_sessions=False)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=ProposalCategoryFactory(event=event),
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        session.refresh_from_db()
        assert session.agenda_item.session_confirmed is False

    @pytest.mark.usefixtures("enrollment_config")
    def test_assign_promotes_waiter(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        waiter = UserFactory(username="t3waiter", email="t3@example.com")
        participation = SessionParticipation.objects.create(
            session=session, user=waiter, status=SessionParticipationStatus.WAITING
        )
        start_time = event.start_time

        authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": (start_time + timedelta(hours=1)).isoformat(),
            },
        )

        participation.refresh_from_db()
        assert participation.status == SessionParticipationStatus.CONFIRMED.value
        assert Notification.objects.filter(
            recipient=waiter, kind=NotificationKind.WAITLIST_PROMOTED.value
        ).exists()

    def test_returns_422_for_rejected_session(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="rejected",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_reassigns_already_scheduled_session_to_new_slot(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        old_space = SpaceFactory(event=event)
        new_space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        old_start = event.start_time
        old_end = old_start + timedelta(hours=1)
        AgendaItemFactory(
            session=session, space=old_space, start_time=old_start, end_time=old_end
        )
        session.status = "scheduled"
        session.save()
        new_start = old_start + timedelta(hours=2)
        new_end = new_start + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": new_space.pk,
                "start_time": new_start.isoformat(),
                "end_time": new_end.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        session.refresh_from_db()
        assert session.status == "scheduled"
        agenda_item = session.agenda_item
        assert agenda_item.space_id == new_space.pk
        assert agenda_item.start_time == new_start
        assert agenda_item.end_time == new_end

    def test_returns_422_for_session_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        other_event = EventFactory(sphere=sphere)
        other_session = SessionFactory(
            category=ProposalCategoryFactory(event=other_event),
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": other_session.pk,
                "space_pk": space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        other_session.refresh_from_db()
        assert other_session.status == "pending"
        assert not AgendaItem.objects.filter(session=other_session).exists()

    def test_returns_422_for_space_from_another_event(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        foreign_space = SpaceFactory(event=EventFactory(sphere=sphere))
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_url(event),
            {
                "session_pk": session.pk,
                "space_pk": foreign_space.pk,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        session.refresh_from_db()
        assert session.status == "pending"
        assert not AgendaItem.objects.filter(session=session).exists()


class TestTimetableUnassignView:
    """Tests for /panel/event/<slug>/timetable/do/unassign/ POST endpoint."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-unassign", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, {})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_on_invalid_event_slug(
        self, authenticated_client, active_user, sphere
    ):
        sphere.managers.add(active_user)
        url = reverse("panel:timetable-unassign", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, {})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_returns_422_on_missing_params(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), {})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_unassigns_session_and_returns_204(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(event=event)
        session = SessionFactory(
            category=proposal_category,
            status="scheduled",
            participants_limit=10,
            min_age=0,
        )
        start_time = event.start_time
        end_time = start_time + timedelta(hours=1)
        AgendaItemFactory(
            session=session, space=space, start_time=start_time, end_time=end_time
        )

        response = authenticated_client.post(
            self.get_url(event), {"session_pk": session.pk}
        )

        assert response.status_code == HTTPStatus.NO_CONTENT
        assert response.get("HX-Trigger") is not None
        session.refresh_from_db()
        assert session.status == "pending"

    def test_returns_422_for_unscheduled_session(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        session = SessionFactory(
            category=proposal_category,
            status="pending",
            participants_limit=10,
            min_age=0,
        )

        response = authenticated_client.post(
            self.get_url(event), {"session_pk": session.pk}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_returns_422_for_session_from_another_event(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_event = EventFactory(sphere=sphere)
        other_space = SpaceFactory(event=other_event)
        other_session = SessionFactory(
            category=ProposalCategoryFactory(event=other_event),
            status="scheduled",
            participants_limit=10,
            min_age=0,
        )
        start_time = other_event.start_time
        end_time = start_time + timedelta(hours=1)
        AgendaItemFactory(
            session=other_session,
            space=other_space,
            start_time=start_time,
            end_time=end_time,
        )

        response = authenticated_client.post(
            self.get_url(event), {"session_pk": other_session.pk}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        other_session.refresh_from_db()
        assert other_session.status == "scheduled"
        assert AgendaItem.objects.filter(session=other_session).exists()
