from datetime import timedelta
from http import HTTPStatus

from django.contrib import messages
from django.urls import reverse

from ludamus.adapters.db.django.models import AgendaItem, ScheduleChangeLog
from tests.integration.conftest import (
    AgendaItemFactory,
    AreaFactory,
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SpaceFactory,
    SphereFactory,
    VenueFactory,
)
from tests.integration.utils import assert_response

PERMISSION_ERROR = "You don't have permission to access the backoffice panel."


class TestTimetableRevertView:
    """Tests for /panel/event/<slug>/timetable/do/revert/ revert endpoint."""

    @staticmethod
    def get_url(event):
        return reverse("panel:timetable-revert", kwargs={"slug": event.slug})

    @staticmethod
    def get_log_url(event):
        return reverse("panel:timetable-log", kwargs={"slug": event.slug})

    @staticmethod
    def get_assign_url(event):
        return reverse("panel:timetable-assign", kwargs={"slug": event.slug})

    @staticmethod
    def get_unassign_url(event):
        return reverse("panel:timetable-unassign", kwargs={"slug": event.slug})

    def test_redirects_anonymous_user_to_login(self, client, event):
        url = self.get_url(event)

        response = client.post(url, data={"log_pk": 1})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={url}"
        )

    def test_redirects_non_manager_user(self, authenticated_client, event):
        response = authenticated_client.post(self.get_url(event), data={"log_pk": 1})

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
        url = reverse("panel:timetable-revert", kwargs={"slug": "nonexistent"})

        response = authenticated_client.post(url, data={"log_pk": 1})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, "Event not found.")],
            url="/panel/",
        )

    def test_missing_log_pk_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.get_url(event), data={})

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_invalid_log_pk_returns_422(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": 99999}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_assign_rejects_session_from_another_sphere(
        self, authenticated_client, active_user, sphere, event, area
    ):
        sphere.managers.add(active_user)
        other_sphere = SphereFactory()
        other_event = EventFactory(sphere=other_sphere)
        other_category = ProposalCategoryFactory(event=other_event)
        other_session = SessionFactory(
            category=other_category,
            sphere=other_sphere,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        space = SpaceFactory(area=area)
        start = event.start_time
        end = start + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": other_session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_session.refresh_from_db()
        assert other_session.status == "pending"
        assert not AgendaItem.objects.filter(session=other_session).exists()

    def test_assign_rejects_space_from_another_sphere(
        self, authenticated_client, active_user, sphere, event, proposal_category
    ):
        sphere.managers.add(active_user)
        other_sphere = SphereFactory()
        other_event = EventFactory(sphere=other_sphere)
        other_venue = VenueFactory(event=other_event)
        other_area = AreaFactory(venue=other_venue)
        other_space = SpaceFactory(area=other_area)
        session = SessionFactory(
            category=proposal_category,
            sphere=sphere,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)

        response = authenticated_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": other_space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        session.refresh_from_db()
        assert session.status == "pending"
        assert not AgendaItem.objects.filter(session=session).exists()

    def test_unassign_rejects_session_from_another_sphere(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_sphere = SphereFactory()
        other_event = EventFactory(sphere=other_sphere)
        other_category = ProposalCategoryFactory(event=other_event)
        other_venue = VenueFactory(event=other_event)
        other_area = AreaFactory(venue=other_venue)
        other_space = SpaceFactory(area=other_area)
        other_session = SessionFactory(
            category=other_category,
            sphere=other_sphere,
            status="scheduled",
            participants_limit=5,
            min_age=0,
        )
        agenda_item = AgendaItemFactory(session=other_session, space=other_space)

        response = authenticated_client.post(
            self.get_unassign_url(event), data={"session_pk": other_session.pk}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_session.refresh_from_db()
        assert other_session.status == "scheduled"
        assert AgendaItem.objects.filter(pk=agenda_item.pk).exists()

    def test_revert_rejects_log_from_another_sphere(
        self, authenticated_client, active_user, sphere, event
    ):
        sphere.managers.add(active_user)
        other_sphere = SphereFactory()
        other_event = EventFactory(sphere=other_sphere)
        other_category = ProposalCategoryFactory(event=other_event)
        other_venue = VenueFactory(event=other_event)
        other_area = AreaFactory(venue=other_venue)
        other_space = SpaceFactory(area=other_area)
        other_session = SessionFactory(
            category=other_category,
            sphere=other_sphere,
            status="scheduled",
            participants_limit=5,
            min_age=0,
        )
        start = other_event.start_time
        end = start + timedelta(hours=1)
        agenda_item = AgendaItemFactory(
            session=other_session, space=other_space, start_time=start, end_time=end
        )
        log = ScheduleChangeLog.objects.create(
            event=other_event,
            session=other_session,
            action="assign",
            new_space=other_space,
            new_start_time=start,
            new_end_time=end,
        )

        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": log.pk}
        )

        assert_response(response, HTTPStatus.UNPROCESSABLE_ENTITY)
        other_session.refresh_from_db()
        assert other_session.status == "scheduled"
        assert AgendaItem.objects.filter(pk=agenda_item.pk).exists()

    def test_revert_assign_unschedules_session(
        self, authenticated_client, active_user, sphere, event, proposal_category, area
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(area=area)
        session = SessionFactory(
            category=proposal_category,
            sphere=sphere,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)

        # Assign the session
        authenticated_client.post(
            self.get_assign_url(event),
            data={
                "session_pk": session.pk,
                "space_pk": space.pk,
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
            },
        )

        # Get the assign log entry pk
        log_response = authenticated_client.get(self.get_log_url(event))
        assign_log = log_response.context["logs"][0]
        assert assign_log.action == "assign"

        # Revert
        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": assign_log.pk}
        )

        assert response.status_code == HTTPStatus.FOUND

        # After revert: log shows REVERT entry, session should be unscheduled
        log_response = authenticated_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        # Most recent is REVERT
        assert logs[0].action == "revert"

    def test_revert_unassign_reschedules_session(
        self, authenticated_client, active_user, sphere, event, proposal_category, area
    ):
        sphere.managers.add(active_user)
        space = SpaceFactory(area=area)
        session = SessionFactory(
            category=proposal_category,
            sphere=sphere,
            status="pending",
            participants_limit=5,
            min_age=0,
        )
        start = event.start_time
        end = start + timedelta(hours=1)
        AgendaItemFactory(session=session, space=space, start_time=start, end_time=end)
        session.status = "scheduled"
        session.save()

        # Unassign the session (creates log)
        authenticated_client.post(
            self.get_unassign_url(event), data={"session_pk": session.pk}
        )

        # Get the unassign log entry pk
        log_response = authenticated_client.get(self.get_log_url(event))
        unassign_log = log_response.context["logs"][0]
        assert unassign_log.action == "unassign"

        # Revert the unassign
        response = authenticated_client.post(
            self.get_url(event), data={"log_pk": unassign_log.pk}
        )

        assert response.status_code == HTTPStatus.FOUND

        # After revert: log shows REVERT entry
        log_response = authenticated_client.get(self.get_log_url(event))
        logs = log_response.context["logs"]
        assert logs[0].action == "revert"
