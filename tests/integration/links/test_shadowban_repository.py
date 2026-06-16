import pytest
from django.db import IntegrityError

from ludamus.adapters.db.django.models import (
    SessionParticipation,
    SessionParticipationStatus,
    Shadowban,
)
from ludamus.links.db.django.safety import ShadowbanRepository
from ludamus.pacts import NotFoundError
from tests.integration.conftest import SessionFactory, UserFactory


class TestShadowbanConstraints:
    def test_self_shadowban_rejected_by_db(self, active_user):
        with pytest.raises(IntegrityError):
            Shadowban.objects.create(owner=active_user, target=active_user)


class TestSetShadowban:
    def test_add_and_remove_by_slug(self, active_user):
        target = UserFactory(username="t1", email="t1@example.com", name="T One")

        ShadowbanRepository.set_shadowban(
            owner_id=active_user.pk, target_slug=target.slug, banned=True
        )
        assert list(active_user.shadowbanned.all()) == [target]

        ShadowbanRepository.set_shadowban(
            owner_id=active_user.pk, target_slug=target.slug, banned=False
        )
        assert not active_user.shadowbanned.exists()

    def test_unknown_slug_raises_not_found(self, active_user):
        with pytest.raises(NotFoundError):
            ShadowbanRepository.set_shadowban(
                owner_id=active_user.pk, target_slug="ghost", banned=True
            )

    def test_self_ban_is_noop(self, active_user):
        ShadowbanRepository.set_shadowban(
            owner_id=active_user.pk, target_slug=active_user.slug, banned=True
        )

        assert not active_user.shadowbanned.exists()


class TestReadEventSignup:
    def test_returns_none_without_signed_up_ids(self):
        assert (
            ShadowbanRepository.read_event_signup(session_id=1, signed_up_ids=[])
            is None
        )

    def test_returns_none_for_unscheduled_session(self, sphere):
        # A session with no agenda item is not on any event timetable.
        session = SessionFactory(sphere=sphere)

        assert (
            ShadowbanRepository.read_event_signup(
                session_id=session.pk, signed_up_ids=[1]
            )
            is None
        )


class TestListSessionShadowbanned:
    def test_returns_banned_participants_with_ban_date(self, active_user, sphere):
        player = UserFactory(
            username="bp", email="bp@example.com", name="Banned Player"
        )
        other = UserFactory(username="op", email="op@example.com", name="Other Player")
        active_user.shadowbanned.add(player)
        session = SessionFactory(sphere=sphere)
        SessionParticipation.objects.create(
            session=session,
            user=player,
            status=SessionParticipationStatus.CONFIRMED.value,
        )
        SessionParticipation.objects.create(
            session=session,
            user=other,
            status=SessionParticipationStatus.CONFIRMED.value,
        )

        warnings = ShadowbanRepository.list_session_shadowbanned(
            viewer_id=active_user.pk, session_id=session.pk
        )

        assert [w.user.pk for w in warnings] == [player.pk]
        assert warnings[0].shadowbanned_at is not None

    def test_empty_when_no_banned_participants(self, active_user, sphere):
        player = UserFactory(username="np", email="np@example.com", name="Nice Player")
        session = SessionFactory(sphere=sphere)
        SessionParticipation.objects.create(
            session=session,
            user=player,
            status=SessionParticipationStatus.CONFIRMED.value,
        )

        assert (
            ShadowbanRepository.list_session_shadowbanned(
                viewer_id=active_user.pk, session_id=session.pk
            )
            == []
        )
