from datetime import UTC, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from ludamus.adapters.db.django.models import (
    Notification,
    Party,
    PartyMembership,
    ScheduleChangeAction,
    ScheduleChangeLog,
    TimeSlot,
)
from ludamus.pacts.legacy import NotificationKind
from tests.integration.conftest import EventFactory


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
