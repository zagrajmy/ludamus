from datetime import UTC, datetime, timedelta

from ludamus.links.db.django.models import Facilitator, SessionField, SessionFieldValue
from ludamus.links.db.django.repositories import ReusableSessionRepository
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    SphereFactory,
    UserFactory,
)


def _session(*, event, **kwargs):
    return SessionFactory(category=ProposalCategoryFactory(event=event), **kwargs)


def _list(*, user, sphere, current, limit=5):
    return ReusableSessionRepository.list_reusable(
        user_id=user.pk, sphere_id=sphere.pk, exclude_event_id=current.pk, limit=limit
    )


class TestListReusable:
    def test_offers_only_the_users_sessions_from_the_spheres_other_events(self):
        user = UserFactory()
        sphere = SphereFactory()
        current = EventFactory(sphere=sphere)
        past = EventFactory(sphere=sphere)
        own = _session(event=past, presenter=user, title="Own")
        _session(event=past, title="Someone else's")
        _session(event=current, presenter=user, title="Proposed here already")
        _session(event=EventFactory(), presenter=user, title="Another sphere")

        found = _list(user=user, sphere=sphere, current=current)

        assert [s.pk for s in found] == [own.pk]

    def test_counts_a_session_the_user_facilitates_without_presenting(self):
        user = UserFactory()
        sphere = SphereFactory()
        past = EventFactory(sphere=sphere)
        imported = _session(event=past, presenter=None, title="Imported")
        imported.facilitators.add(
            Facilitator.objects.create(
                event=past, user=user, display_name="Ola", slug="ola"
            )
        )

        found = _list(user=user, sphere=sphere, current=EventFactory(sphere=sphere))

        assert [s.pk for s in found] == [imported.pk]

    def test_skips_a_session_held_only_through_a_deleted_facilitator(self):
        user = UserFactory()
        sphere = SphereFactory()
        past = EventFactory(sphere=sphere)
        session = _session(event=past, presenter=None)
        facilitator = Facilitator.objects.create(
            event=past, user=user, display_name="Ola", slug="ola"
        )
        session.facilitators.add(facilitator)
        facilitator.soft_delete()

        found = _list(user=user, sphere=sphere, current=EventFactory(sphere=sphere))

        assert not found

    def test_offers_a_repeated_session_once_from_its_newest_edition(self):
        user = UserFactory()
        sphere = SphereFactory()
        now = datetime.now(UTC)
        older = EventFactory(sphere=sphere, start_time=now - timedelta(days=60))
        newer = EventFactory(sphere=sphere, start_time=now - timedelta(days=30))
        _session(event=older, presenter=user, title="Mothership")
        latest = _session(event=newer, presenter=user, title="mothership ")

        found = _list(user=user, sphere=sphere, current=EventFactory(sphere=sphere))

        assert [s.pk for s in found] == [latest.pk]

    def test_stops_at_the_limit_with_the_newest(self):
        user = UserFactory()
        sphere = SphereFactory()
        now = datetime.now(UTC)
        older = EventFactory(sphere=sphere, start_time=now - timedelta(days=60))
        newer = EventFactory(sphere=sphere, start_time=now - timedelta(days=30))
        _session(event=older, presenter=user, title="Older")
        newest = _session(event=newer, presenter=user, title="Newer")

        found = _list(
            user=user, sphere=sphere, current=EventFactory(sphere=sphere), limit=1
        )

        assert [s.pk for s in found] == [newest.pk]

    def test_carries_answers_by_field_slug(self):
        user = UserFactory()
        sphere = SphereFactory()
        past = EventFactory(sphere=sphere)
        session = _session(event=past, presenter=user)
        field = SessionField.objects.create(
            event=past, name="System", question="Which system?", slug="system"
        )
        SessionFieldValue.objects.create(session=session, field=field, value="Fate")

        found = _list(user=user, sphere=sphere, current=EventFactory(sphere=sphere))

        assert [s.field_values for s in found] == [{"system": "Fate"}]
