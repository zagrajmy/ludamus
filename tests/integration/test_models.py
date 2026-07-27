from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from ludamus.links.db.django.models import (
    Notification,
    Party,
    PartyMembership,
    ScheduleChangeAction,
    ScheduleChangeLog,
    TimeSlot,
)
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import EnrollmentConfigFactory, EventFactory


class TestEventIsPublished:
    def test_published_when_publication_time_in_past(self, sphere):
        event = EventFactory(
            sphere=sphere, publication_time=datetime.now(UTC) - timedelta(days=1)
        )
        assert event.is_published is True

    def test_not_published_when_publication_time_in_future(self, sphere):
        event = EventFactory(
            sphere=sphere, publication_time=datetime.now(UTC) + timedelta(days=1)
        )
        assert event.is_published is False

    def test_not_published_when_publication_time_is_none(self, sphere):
        event = EventFactory(sphere=sphere, publication_time=None)
        assert event.is_published is False


class TestTimeSlot:
    def test_validate_unique_ok(self, event, faker):
        TimeSlot.objects.create(
            event=event,
            start_time=faker.date_time_between("+1h", "+2h"),
            end_time=faker.date_time_between("+3h", "+4h"),
        )
        TimeSlot(
            event=event,
            start_time=faker.date_time_between("+5h", "+6h"),
            end_time=faker.date_time_between("+7h", "+8h"),
        ).full_clean()

    def test_validate_unique_error_start_inside(self, event, faker):
        TimeSlot.objects.create(
            event=event,
            start_time=faker.date_time_between("+3h", "+4h"),
            end_time=faker.date_time_between("+7h", "+8h"),
        )
        with pytest.raises(ValidationError):
            TimeSlot(
                event=event,
                start_time=faker.date_time_between("+1h", "+2h"),
                end_time=faker.date_time_between("+5h", "+6h"),
            ).full_clean()

    def test_validate_unique_error_end_inside(self, event, faker):
        TimeSlot.objects.create(
            event=event,
            start_time=faker.date_time_between("+3h", "+4h"),
            end_time=faker.date_time_between("+7h", "+8h"),
        )
        with pytest.raises(ValidationError):
            TimeSlot(
                event=event,
                start_time=faker.date_time_between("+5h", "+6h"),
                end_time=faker.date_time_between("+9h", "+10h"),
            ).full_clean()

    def test_validate_unique_error_contains(self, event, faker):
        TimeSlot.objects.create(
            event=event,
            start_time=faker.date_time_between("+1h", "+2h"),
            end_time=faker.date_time_between("+7h", "+8h"),
        )
        with pytest.raises(ValidationError):
            TimeSlot(
                event=event,
                start_time=faker.date_time_between("+3h", "+4h"),
                end_time=faker.date_time_between("+5h", "+6h"),
            ).full_clean()


class TestModelStringRepresentations:
    def test_notification_str(self, waiter):
        kind = NotificationKind.WAITLIST_OFFER.value
        notification = Notification.objects.create(
            recipient=waiter, kind=kind, title="You have an offer"
        )

        assert str(notification) == f"{kind} for {waiter.name}"

    def test_schedule_change_log_str(self, event, session, active_user):
        action = ScheduleChangeAction.ASSIGN.value
        log = ScheduleChangeLog.objects.create(
            event=event, session=session, user=active_user, action=action
        )

        assert str(log) == f"{action} {session} by {active_user}"

    def test_unnamed_party_and_membership_str(self, active_user):
        party = Party.objects.create(leader=active_user, name="")
        membership = PartyMembership.objects.create(party=party, member=active_user)

        assert str(party) == f"party (#{party.pk})"
        assert str(membership) == f"{active_user.pk} in party {party.pk}"

    def test_named_party_str(self, active_user):
        party = Party.objects.create(leader=active_user, name="Drużyna")

        assert str(party) == f"Drużyna (#{party.pk})"


class TestPartyMembershipConstraint:
    def test_member_unique_per_party(self, active_user):
        party = Party.objects.create(leader=active_user, name="")
        PartyMembership.objects.create(party=party, member=active_user)

        with pytest.raises(IntegrityError), transaction.atomic():
            PartyMembership.objects.create(party=party, member=active_user)


def _active_window(event, **kwargs):
    now = datetime.now(UTC)
    return EnrollmentConfigFactory(
        event=event,
        start_time=now - timedelta(days=1),
        end_time=now + timedelta(days=5),
        **kwargs,
    )


class TestEventRestrictsToConfiguredUsers:
    def test_false_without_any_active_window(self, event):
        assert event.restricts_to_configured_users() is False

    def test_true_when_the_only_window_restricts(self, event):
        _active_window(event, restrict_to_configured_users=True)

        assert event.restricts_to_configured_users() is True

    def test_false_when_the_only_window_does_not_restrict(self, event):
        _active_window(event, restrict_to_configured_users=False)

        assert event.restricts_to_configured_users() is False

    def test_false_when_an_overlapping_window_stays_open(self, event):
        _active_window(event, restrict_to_configured_users=True, percentage_slots=100)
        _active_window(event, restrict_to_configured_users=False, percentage_slots=50)

        assert event.restricts_to_configured_users() is False

    def test_true_when_every_overlapping_window_restricts(self, event):
        _active_window(event, restrict_to_configured_users=True, percentage_slots=100)
        _active_window(event, restrict_to_configured_users=True, percentage_slots=50)

        assert event.restricts_to_configured_users() is True

    def test_ignores_inactive_windows(self, event):
        now = datetime.now(UTC)
        _active_window(event, restrict_to_configured_users=False)
        EnrollmentConfigFactory(
            event=event,
            start_time=now - timedelta(days=10),
            end_time=now - timedelta(days=9),
            restrict_to_configured_users=True,
        )

        assert event.restricts_to_configured_users() is False


class TestEventMaxWaitlistSessions:
    def test_zero_without_any_active_window(self, event):
        assert event.max_waitlist_sessions() == 0

    def test_takes_the_highest_across_overlapping_windows(self, event):
        highest = 5
        _active_window(event, max_waitlist_sessions=2)
        _active_window(event, max_waitlist_sessions=highest, percentage_slots=10)

        assert event.max_waitlist_sessions() == highest
