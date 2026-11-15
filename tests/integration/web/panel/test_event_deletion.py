from datetime import timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.contrib.admin import helpers
from django.urls import reverse
from django.utils import timezone

from ludamus.links.db.django.models import (
    Event,
    EventDeletionApproval,
    Notification,
    Session,
    SphereMembership,
)
from ludamus.pacts.notifications import NotificationKind
from ludamus.pacts.sphere import SphereRole
from tests.integration.conftest import (
    EventFactory,
    SessionFactory,
    SphereFactory,
    UserFactory,
)
from tests.integration.utils import FormErrorsMatcher, assert_response
from tests.integration.web.panel.helpers import (
    READ_ONLY_ROLE_ERROR,
    assert_event_not_found,
    panel_context,
    settings_tab_urls,
)

ONLY_MANAGERS_ERROR = "Only sphere managers can delete an event."
NAME_MISMATCH_ERROR = "The name you typed does not match."
REQUIRED = "Type the event's name to confirm."
ONE_MORE_NEEDED = (
    "Your approval is in. The event is deleted once 1 more manager approves."
)


def _approve_url(event):
    return reverse("panel:event-approve-deletion", kwargs={"slug": event.slug})


def _withdraw_url(event):
    return reverse("panel:event-withdraw-deletion", kwargs={"slug": event.slug})


def _ballot_url(event):
    settings_url = reverse("panel:event-settings", kwargs={"slug": event.slug})
    return f"{settings_url}#event-deletion"


def _add_managers(sphere, count):
    managers = [UserFactory() for _ in range(count)]
    for manager in managers:
        sphere.managers.add(manager)
    return managers


def _is_deleted(event):
    return Event.all_objects.get(pk=event.pk).deleted_at is not None


@pytest.mark.django_db
class TestApproveDeletion:
    def test_a_solo_manager_deletes_the_event_and_hides_its_sessions(
        self, panel_client, event
    ):
        session = SessionFactory(event=event, category=None)

        response = panel_client.post(_approve_url(event), {"event_name": event.name})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"{event.name} is deleted.")],
            url="/panel/",
        )
        assert _is_deleted(event)
        assert not Session.objects.filter(pk=session.pk).exists()

    def test_first_of_two_managers_asks_and_the_other_is_notified(
        self, panel_client, event, sphere, active_user
    ):
        (other,) = _add_managers(sphere, 1)

        response = panel_client.post(_approve_url(event), {"event_name": event.name})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, ONE_MORE_NEEDED)],
            url=_ballot_url(event),
        )
        assert not _is_deleted(event)
        assert list(
            EventDeletionApproval.objects.values_list("event_id", "user_id")
        ) == [(event.pk, active_user.pk)]
        assert list(
            Notification.objects.values_list("recipient_id", "kind", "title")
        ) == [
            (
                other.pk,
                NotificationKind.EVENT_DELETION_REQUESTED,
                f"{active_user.name} wants to delete {event.name}",
            )
        ]

    def test_second_of_two_managers_completes_the_deletion(
        self, panel_client, event, sphere
    ):
        (other,) = _add_managers(sphere, 1)
        EventDeletionApproval.objects.create(event=event, user=other)

        response = panel_client.post(_approve_url(event), {"event_name": event.name})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"{event.name} is deleted.")],
            url="/panel/",
        )
        assert _is_deleted(event)

    def test_seven_managers_need_four_approvals(self, panel_client, event, sphere):
        first, second, *_rest = _add_managers(sphere, 6)
        for approver in (first, second):
            EventDeletionApproval.objects.create(event=event, user=approver)

        response = panel_client.post(_approve_url(event), {"event_name": event.name})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, ONE_MORE_NEEDED)],
            url=_ballot_url(event),
        )
        assert not _is_deleted(event)
        # Only the first approval asks the others; later ones add no noise.
        assert not Notification.objects.exists()

    def test_a_former_managers_approval_does_not_count(
        self, panel_client, event, sphere
    ):
        (former,) = _add_managers(sphere, 1)
        EventDeletionApproval.objects.create(event=event, user=former)
        SphereMembership.objects.filter(sphere=sphere, user=former).delete()
        (_still_here,) = _add_managers(sphere, 1)

        response = panel_client.post(_approve_url(event), {"event_name": event.name})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, ONE_MORE_NEEDED)],
            url=_ballot_url(event),
        )
        assert not _is_deleted(event)

    def test_a_superuser_off_the_team_cannot_approve(self, client, event):
        client.force_login(UserFactory(is_superuser=True, is_staff=True))

        response = client.post(_approve_url(event), {"event_name": event.name})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.ERROR, ONLY_MANAGERS_ERROR)],
            url=_ballot_url(event),
        )
        assert not _is_deleted(event)
        assert not EventDeletionApproval.objects.exists()

    @pytest.mark.parametrize("typed", ("", "Some other event"))
    def test_a_name_that_does_not_match_records_nothing(
        self, panel_client, event, typed
    ):
        response = panel_client.post(_approve_url(event), {"event_name": typed})

        assert_response(
            response,
            HTTPStatus.OK,
            template_name="panel/settings.html",
            context_data={
                **panel_context(event, active_nav="settings"),
                "is_proposal_active": response.context["is_proposal_active"],
                "active_tab": "general",
                "tab_urls": settings_tab_urls(event),
                "form": ANY,
                "deletion": response.context["deletion"],
                "deletion_form": FormErrorsMatcher(
                    event_name=[NAME_MISMATCH_ERROR if typed else REQUIRED]
                ),
            },
        )
        assert not _is_deleted(event)
        assert not EventDeletionApproval.objects.exists()

    def test_spaces_around_the_typed_name_are_forgiven(self, panel_client, event):
        response = panel_client.post(
            _approve_url(event), {"event_name": f"  {event.name} "}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, f"{event.name} is deleted.")],
            url="/panel/",
        )

    def test_an_event_of_another_sphere_is_not_found(self, panel_client):
        foreign = EventFactory(sphere=SphereFactory())

        response = panel_client.post(
            _approve_url(foreign), {"event_name": foreign.name}
        )

        assert_event_not_found(response)
        assert not _is_deleted(foreign)
        assert not EventDeletionApproval.objects.exists()

    def test_a_deleted_event_is_not_found(self, panel_client, event):
        Event.objects.filter(pk=event.pk).update(deleted_at=timezone.now())

        response = panel_client.post(_approve_url(event), {"event_name": event.name})

        assert_event_not_found(response)


@pytest.mark.django_db
class TestWithdrawDeletion:
    def test_withdrawing_takes_the_approval_back(
        self, panel_client, event, sphere, active_user
    ):
        _add_managers(sphere, 1)
        EventDeletionApproval.objects.create(event=event, user=active_user)

        response = panel_client.post(_withdraw_url(event))

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Your approval is withdrawn.")],
            url=_ballot_url(event),
        )
        assert not EventDeletionApproval.objects.exists()

    def test_an_event_of_another_sphere_is_not_found(self, panel_client, active_user):
        foreign = EventFactory(sphere=SphereFactory())
        EventDeletionApproval.objects.create(event=foreign, user=active_user)

        response = panel_client.post(_withdraw_url(foreign))

        assert_event_not_found(response)
        assert EventDeletionApproval.objects.filter(event=foreign).exists()


@pytest.mark.django_db
class TestDeletedEvent:
    def test_its_public_page_is_unavailable(self, client, event):
        Event.objects.filter(pk=event.pk).update(deleted_at=timezone.now())

        response = client.get(
            reverse("web:chronology:event", kwargs={"slug": event.slug})
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse("web:index"),
            messages=[(messages.INFO, "That event isn't available.")],
        )

    def test_staff_restore_it_with_the_sessions_it_hid(self, client, event, sphere):
        deleted_earlier = SessionFactory(event=event, category=None)
        Session.objects.filter(pk=deleted_earlier.pk).update(
            deleted_at=timezone.now() - timedelta(days=1)
        )
        hidden_with_event = SessionFactory(event=event, category=None)
        approver = UserFactory()
        sphere.managers.add(approver)
        EventDeletionApproval.objects.create(event=event, user=approver)
        stamp = timezone.now()
        Session.objects.filter(event=event).update(deleted_at=stamp)
        Event.objects.filter(pk=event.pk).update(deleted_at=stamp)
        client.force_login(UserFactory(is_staff=True, is_superuser=True))

        response = client.post(
            reverse("admin:db_main_event_changelist"),
            {"action": "restore_events", helpers.ACTION_CHECKBOX_NAME: [event.pk]},
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=[(messages.SUCCESS, "Restored 1 event(s).")],
            url=reverse("admin:db_main_event_changelist"),
        )
        assert Event.objects.filter(pk=event.pk).exists()
        assert set(
            Session.objects.filter(event=event).values_list("pk", flat=True)
        ) == {hidden_with_event.pk}
        assert not EventDeletionApproval.objects.exists()


@pytest.mark.django_db
def test_comms_member_cannot_approve(authenticated_client, active_user, event, sphere):
    SphereMembership.objects.create(
        sphere=sphere, user=active_user, role=SphereRole.COMMS
    )

    response = authenticated_client.post(
        _approve_url(event), {"event_name": event.name}
    )

    assert_response(
        response,
        HTTPStatus.FOUND,
        messages=[(messages.ERROR, READ_ONLY_ROLE_ERROR)],
        url="/",
    )
    assert not EventDeletionApproval.objects.exists()
