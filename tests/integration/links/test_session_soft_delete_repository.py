import pytest

from ludamus.adapters.db.django.models import Session
from ludamus.links.db.django.repositories import SessionRepository
from ludamus.pacts import NotFoundError
from tests.integration.conftest import SessionFactory


class TestSessionRepositorySoftDelete:
    def test_soft_delete_sets_deleted_at(self, sphere):
        session = SessionFactory(sphere=sphere)

        SessionRepository.soft_delete(session.pk)

        dead = Session.all_objects.get(pk=session.pk)
        assert dead.deleted_at is not None

    def test_default_manager_excludes_soft_deleted(self, sphere):
        session = SessionFactory(sphere=sphere)

        SessionRepository.soft_delete(session.pk)

        assert not Session.objects.filter(pk=session.pk).exists()

    def test_all_objects_includes_soft_deleted(self, sphere):
        session = SessionFactory(sphere=sphere)

        SessionRepository.soft_delete(session.pk)

        assert Session.all_objects.filter(pk=session.pk).exists()

    def test_repository_read_raises_not_found_for_soft_deleted(self, sphere):
        session = SessionFactory(sphere=sphere)

        SessionRepository.soft_delete(session.pk)

        with pytest.raises(NotFoundError):
            SessionRepository.read(session.pk)

    def test_restore_brings_session_back_to_default_manager(self, sphere):
        session = SessionFactory(sphere=sphere)
        SessionRepository.soft_delete(session.pk)

        Session.all_objects.get(pk=session.pk).restore()

        restored = Session.objects.get(pk=session.pk)
        assert restored.deleted_at is None

    def test_soft_delete_already_deleted_raises_not_found(self, sphere):
        session = SessionFactory(sphere=sphere)
        SessionRepository.soft_delete(session.pk)

        with pytest.raises(NotFoundError):
            SessionRepository.soft_delete(session.pk)

    def test_soft_delete_missing_session_raises_not_found(self):
        with pytest.raises(NotFoundError):
            SessionRepository.soft_delete(999999)
