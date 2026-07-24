from ludamus.links.db.django.repositories import SessionRepository
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    UserFactory,
)


class TestListReusableForUser:
    def test_returns_users_sessions_from_other_events_newest_first(self):
        user = UserFactory()
        old = SessionFactory(presenter=user, title="Old Game")
        new = SessionFactory(presenter=user, title="New Game")
        target_event = EventFactory()

        result = SessionRepository.list_reusable_for_user(
            user_id=user.pk, exclude_event_id=target_event.pk
        )

        assert [r.pk for r in result] == [new.pk, old.pk]
        assert result[0].title == "New Game"
        assert result[0].event_name == new.event.name
        assert result[0].category_name == new.category.name

    def test_excludes_current_event_and_other_users(self):
        user = UserFactory()
        stranger = UserFactory()
        target_category = ProposalCategoryFactory()
        target_event = target_category.event
        SessionFactory(
            presenter=user, category=target_category, event=target_event,
            title="Already Proposed Here",
        )
        SessionFactory(presenter=stranger, title="Someone Else's")
        keeper = SessionFactory(presenter=user, title="Reusable")

        result = SessionRepository.list_reusable_for_user(
            user_id=user.pk, exclude_event_id=target_event.pk
        )

        assert [r.pk for r in result] == [keeper.pk]
