import pytest

from ludamus.links.db.django.repositories import ShadowbanRepository
from ludamus.pacts import NotFoundError
from tests.integration.conftest import SessionFactory, UserFactory


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
