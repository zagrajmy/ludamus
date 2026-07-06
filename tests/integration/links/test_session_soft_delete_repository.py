import pytest

from ludamus.adapters.db.django.models import Session
from ludamus.links.db.django.repositories import SessionRepository
from ludamus.pacts import NotFoundError
from tests.integration.conftest import ProposalCategoryFactory, SessionFactory


class TestSessionRepositorySoftDelete:
    def test_soft_delete_sets_deleted_at(self):
        session = SessionFactory()

        SessionRepository.soft_delete(session.pk)

        dead = Session.all_objects.get(pk=session.pk)
        assert dead.deleted_at is not None

    def test_default_manager_excludes_soft_deleted(self):
        session = SessionFactory()

        SessionRepository.soft_delete(session.pk)

        assert not Session.objects.filter(pk=session.pk).exists()

    def test_all_objects_includes_soft_deleted(self):
        session = SessionFactory()

        SessionRepository.soft_delete(session.pk)

        assert Session.all_objects.filter(pk=session.pk).exists()

    def test_repository_read_raises_not_found_for_soft_deleted(self):
        session = SessionFactory()

        SessionRepository.soft_delete(session.pk)

        with pytest.raises(NotFoundError):
            SessionRepository.read(session.pk)

    def test_restore_brings_session_back_to_default_manager(self):
        session = SessionFactory()
        SessionRepository.soft_delete(session.pk)

        Session.all_objects.get(pk=session.pk).restore()

        restored = Session.objects.get(pk=session.pk)
        assert restored.deleted_at is None

    def test_soft_delete_already_deleted_raises_not_found(self):
        session = SessionFactory()
        SessionRepository.soft_delete(session.pk)

        with pytest.raises(NotFoundError):
            SessionRepository.soft_delete(session.pk)

    def test_soft_delete_missing_session_raises_not_found(self):
        with pytest.raises(NotFoundError):
            SessionRepository.soft_delete(999999)


class TestSessionRepositoryRestore:
    def test_restore_clears_deleted_at(self):
        category = ProposalCategoryFactory()
        session = SessionFactory(category=category)
        SessionRepository.soft_delete(session.pk)

        SessionRepository.restore(session.pk, category.event.pk)

        restored = Session.objects.get(pk=session.pk)
        assert restored.deleted_at is None

    def test_restore_missing_session_raises_not_found(self):
        with pytest.raises(NotFoundError):
            SessionRepository.restore(999999, 999999)

    def test_restore_alive_session_raises_not_found(self):
        category = ProposalCategoryFactory()
        session = SessionFactory(category=category)

        with pytest.raises(NotFoundError):
            SessionRepository.restore(session.pk, category.event.pk)

    def test_restore_wrong_event_raises_not_found(self):
        category = ProposalCategoryFactory()
        other_category = ProposalCategoryFactory()
        session = SessionFactory(category=category)
        SessionRepository.soft_delete(session.pk)

        with pytest.raises(NotFoundError):
            SessionRepository.restore(session.pk, other_category.event.pk)

    def test_restore_reslugs_when_slug_taken_by_live_session(self):
        category = ProposalCategoryFactory()
        session = SessionFactory(category=category, slug="shared")
        SessionRepository.soft_delete(session.pk)
        # A live session reclaims the slug while the original is soft-deleted.
        live = SessionFactory(category=category, slug="shared")

        SessionRepository.restore(session.pk, category.event.pk)

        restored = Session.objects.get(pk=session.pk)
        assert restored.deleted_at is None
        assert restored.slug != "shared"
        assert restored.slug.startswith("shared-")
        assert Session.objects.get(pk=live.pk).slug == "shared"


class TestSessionSlugConstraint:
    def test_new_session_reuses_slug_of_soft_deleted(self):
        category = ProposalCategoryFactory()
        dead = SessionFactory(category=category, slug="reused")
        SessionRepository.soft_delete(dead.pk)

        # No IntegrityError: the alive-only constraint ignores the dead row.
        live = SessionFactory(category=category, slug="reused")

        assert live.pk != dead.pk
        assert (
            Session.objects.filter(
                category__event=category.event, slug="reused"
            ).count()
            == 1
        )


class TestSessionRepositoryListDeletedByEvent:
    def test_returns_only_deleted_sessions_for_event(self):
        category = ProposalCategoryFactory()
        event_pk = category.event.pk
        deleted = SessionFactory(category=category)
        SessionRepository.soft_delete(deleted.pk)
        SessionFactory(category=category)  # alive, same event
        other_deleted = SessionFactory()  # different event
        SessionRepository.soft_delete(other_deleted.pk)

        result = SessionRepository.list_deleted_by_event(event_pk)

        assert [item.pk for item in result] == [deleted.pk]
