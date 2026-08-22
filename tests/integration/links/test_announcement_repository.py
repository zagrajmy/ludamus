import pytest
from django.db import IntegrityError

from ludamus.links.db.django.models import Announcement
from ludamus.links.db.django.repositories import AnnouncementsRepository
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import (
    AnnouncementData,
    AnnouncementDTO,
    AnnouncementScope,
)
from tests.integration.conftest import EventFactory


class TestAnnouncementsRepositoryList:
    def test_list_for_scope_scopes_to_sphere(self, sphere, non_root_sphere):
        mine = Announcement.objects.create(sphere=sphere, title="Mine", content="body")
        Announcement.objects.create(
            sphere=non_root_sphere, title="Other", content="body"
        )

        result = AnnouncementsRepository.list_for_scope(
            AnnouncementScope(sphere_id=sphere.pk)
        )

        assert result == [AnnouncementDTO.model_validate(mine)]

    def test_list_for_scope_orders_newest_first(self, sphere):
        first = Announcement.objects.create(sphere=sphere, title="A", content="b")
        second = Announcement.objects.create(sphere=sphere, title="B", content="b")

        result = AnnouncementsRepository.list_for_scope(
            AnnouncementScope(sphere_id=sphere.pk)
        )

        assert [a.pk for a in result] == [second.pk, first.pk]

    def test_list_published_excludes_drafts(self, sphere):
        published = Announcement.objects.create(
            sphere=sphere, title="Live", content="b", is_published=True
        )
        Announcement.objects.create(
            sphere=sphere, title="Draft", content="b", is_published=False
        )

        result = AnnouncementsRepository.list_published(
            AnnouncementScope(sphere_id=sphere.pk)
        )

        assert result == [AnnouncementDTO.model_validate(published)]


class TestAnnouncementsRepositoryEventScope:
    def test_list_for_scope_excludes_sphere_announcements(self, sphere, event):
        mine = Announcement.objects.create(event=event, title="Mine", content="body")
        Announcement.objects.create(sphere=sphere, title="Sphere", content="body")

        result = AnnouncementsRepository.list_for_scope(
            AnnouncementScope(event_id=event.pk)
        )

        assert result == [AnnouncementDTO.model_validate(mine)]

    def test_sphere_scope_excludes_event_announcements(self, sphere, event):
        Announcement.objects.create(event=event, title="Event", content="body")

        result = AnnouncementsRepository.list_for_scope(
            AnnouncementScope(sphere_id=sphere.pk)
        )

        assert result == []

    def test_create_persists_event(self, event):
        data = AnnouncementData(title="Hello", content="World", is_published=True)

        result = AnnouncementsRepository.create(
            AnnouncementScope(event_id=event.pk), data
        )

        stored = Announcement.objects.get(pk=result.pk)
        assert stored.event_id == event.pk
        assert stored.sphere_id is None

    def test_get_raises_for_other_event(self, sphere, event):
        other = EventFactory(sphere=sphere)
        announcement = Announcement.objects.create(event=other, title="T", content="C")

        with pytest.raises(NotFoundError):
            AnnouncementsRepository.get(
                AnnouncementScope(event_id=event.pk), announcement.pk
            )

    def test_delete_raises_for_other_event(self, sphere, event):
        other = EventFactory(sphere=sphere)
        announcement = Announcement.objects.create(event=other, title="T", content="C")

        with pytest.raises(NotFoundError):
            AnnouncementsRepository.delete(
                AnnouncementScope(event_id=event.pk), announcement.pk
            )

        assert Announcement.objects.filter(pk=announcement.pk).exists()


class TestAnnouncementsRepositoryGet:
    def test_get_returns_dto(self, sphere):
        announcement = Announcement.objects.create(
            sphere=sphere, title="T", content="C"
        )

        result = AnnouncementsRepository.get(
            AnnouncementScope(sphere_id=sphere.pk), announcement.pk
        )

        assert result == AnnouncementDTO.model_validate(announcement)

    def test_get_raises_for_other_sphere(self, sphere, non_root_sphere):
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="T", content="C"
        )

        with pytest.raises(NotFoundError):
            AnnouncementsRepository.get(
                AnnouncementScope(sphere_id=sphere.pk), announcement.pk
            )


class TestAnnouncementsRepositoryWrite:
    def test_create_persists_fields(self, sphere):
        data = AnnouncementData(title="Hello", content="World", is_published=False)

        result = AnnouncementsRepository.create(
            AnnouncementScope(sphere_id=sphere.pk), data
        )

        stored = Announcement.objects.get(pk=result.pk)
        assert stored.title == "Hello"
        assert stored.content == "World"
        assert stored.is_published is False

    def test_update_changes_fields(self, sphere):
        announcement = Announcement.objects.create(
            sphere=sphere, title="Old", content="Old", is_published=True
        )
        data = AnnouncementData(title="New", content="New", is_published=False)

        AnnouncementsRepository.update(
            AnnouncementScope(sphere_id=sphere.pk), announcement.pk, data
        )

        announcement.refresh_from_db()
        assert announcement.title == "New"
        assert announcement.content == "New"
        assert announcement.is_published is False

    def test_update_raises_for_other_sphere(self, sphere, non_root_sphere):
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="T", content="C"
        )
        data = AnnouncementData(title="X", content="X", is_published=True)

        with pytest.raises(NotFoundError):
            AnnouncementsRepository.update(
                AnnouncementScope(sphere_id=sphere.pk), announcement.pk, data
            )

    def test_delete_removes_row(self, sphere):
        announcement = Announcement.objects.create(
            sphere=sphere, title="T", content="C"
        )

        AnnouncementsRepository.delete(
            AnnouncementScope(sphere_id=sphere.pk), announcement.pk
        )

        assert not Announcement.objects.filter(pk=announcement.pk).exists()

    def test_delete_raises_for_other_sphere(self, sphere, non_root_sphere):
        announcement = Announcement.objects.create(
            sphere=non_root_sphere, title="T", content="C"
        )

        with pytest.raises(NotFoundError):
            AnnouncementsRepository.delete(
                AnnouncementScope(sphere_id=sphere.pk), announcement.pk
            )

        assert Announcement.objects.filter(pk=announcement.pk).exists()


class TestAnnouncementScopeConstraint:
    def test_both_owners_are_rejected(self, sphere, event):
        with pytest.raises(IntegrityError):
            Announcement.objects.create(
                sphere=sphere, event=event, title="T", content="C"
            )

    def test_no_owner_is_rejected(self):
        with pytest.raises(IntegrityError):
            Announcement.objects.create(title="T", content="C")
