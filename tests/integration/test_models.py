from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.timezone import localtime

from ludamus.links.db.django.models import (
    DiscountRule,
    Guild,
    GuildMembership,
    Notification,
    Party,
    PartyMembership,
    ScheduleChangeAction,
    ScheduleChangeLog,
    SessionAvailableDay,
    SphereMembership,
    Track,
)
from ludamus.pacts.discounts import DiscountMethod
from ludamus.pacts.legacy import NotificationKind
from ludamus.pacts.multiverse import SphereRole
from tests.integration.conftest import EventFactory, SessionFactory


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


class TestSphereClean:
    def test_rejects_non_list_enabled_pages(self, sphere):
        # A JSON object coerces through membership checks ({"events": true}
        # has "events" as a key) but breaks SphereDTO validation on read.
        sphere.enabled_pages = {"events": True}
        with pytest.raises(ValidationError) as exc_info:
            sphere.full_clean()
        assert "enabled_pages" in exc_info.value.message_dict

    def test_rejects_unknown_page_slug(self, sphere):
        sphere.enabled_pages = ["events", "unknown"]
        with pytest.raises(ValidationError) as exc_info:
            sphere.full_clean()
        assert "enabled_pages" in exc_info.value.message_dict

    def test_rejects_default_page_not_enabled(self, sphere):
        sphere.enabled_pages = ["encounters"]
        sphere.default_page = "events"
        with pytest.raises(ValidationError) as exc_info:
            sphere.full_clean()
        assert "default_page" in exc_info.value.message_dict


class TestSessionAvailableDay:
    @staticmethod
    def _day(event):
        return localtime(event.start_time).date()

    def test_validate_unique_ok_for_another_day(self, event, session):
        day = self._day(event)
        SessionAvailableDay.objects.create(session=session, day=day)

        SessionAvailableDay(session=session, day=day + timedelta(days=1)).full_clean()

    def test_validate_unique_ok_for_another_session(self, event, session):
        day = self._day(event)
        SessionAvailableDay.objects.create(session=session, day=day)

        SessionAvailableDay(
            session=SessionFactory(event=event, category=None), day=day
        ).full_clean()

    def test_validate_unique_error_for_the_same_day_twice(self, event, session):
        # One offer, one answer per day: a duplicate would double-count the
        # session on every day-major read.
        day = self._day(event)
        SessionAvailableDay.objects.create(session=session, day=day)

        with pytest.raises(ValidationError):
            SessionAvailableDay(session=session, day=day).full_clean()


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

    def test_sphere_membership_str(self, active_user, sphere):
        membership = SphereMembership.objects.create(
            sphere=sphere, user=active_user, role=SphereRole.COMMS
        )

        assert str(membership) == f"{active_user.pk} is comms of sphere {sphere.pk}"

    def test_guild_and_membership_str(self, active_user, sphere):
        guild = Guild.objects.create(sphere=sphere, name="Topory", slug="topory")
        membership = GuildMembership.objects.create(
            sphere=sphere, guild=guild, member=active_user
        )

        assert str(guild) == "Topory"
        assert str(membership) == f"{active_user.pk} in guild {guild.pk}"

    def test_discount_rule_str(self, event):
        rule = DiscountRule.objects.create(
            event=event,
            method=DiscountMethod.STARTED_HOURS.value,
            quantity=4,
            percent=Decimal("50.00"),
        )

        assert str(rule) == "started_hours >= 4 -> 50.00%"


class TestTrackNameConstraint:
    def test_name_unique_per_event_ignoring_case(self, event):
        Track.objects.create(event=event, name="RPG", slug="rpg")

        with pytest.raises(IntegrityError), transaction.atomic():
            Track.objects.create(event=event, name="rpg", slug="rpg-2")

    def test_same_name_allowed_in_another_event(self, event, sphere):
        other_event = EventFactory(sphere=sphere)
        Track.objects.create(event=event, name="RPG", slug="rpg")

        Track.objects.create(event=other_event, name="RPG", slug="rpg")

        assert Track.objects.filter(name="RPG", event=other_event).exists()


class TestPartyMembershipConstraint:
    def test_member_unique_per_party(self, active_user):
        party = Party.objects.create(leader=active_user, name="")
        PartyMembership.objects.create(party=party, member=active_user)

        with pytest.raises(IntegrityError), transaction.atomic():
            PartyMembership.objects.create(party=party, member=active_user)
