"""Coverage tests for NotFoundError branches in repositories.

These tests target the `except DoesNotExist: raise NotFoundError` branches
that are otherwise hard to reach from view-level integration tests.
"""

import pytest

from ludamus.adapters.db.django.models import (
    PersonalDataField,
    ProposalCategory,
    Session,
    SessionField,
)
from ludamus.links.db.django.repositories import (
    ConnectedUserRepository,
    EventRepository,
    ProposalCategoryRepository,
    SessionRepository,
    SphereRepository,
    VenueRepository,
)
from ludamus.pacts import EventUpdateData, NotFoundError

MISSING_ID = 99_999_999


class TestSphereRepositoryNotFound:
    def test_read_raises_when_missing(self):
        with pytest.raises(NotFoundError):
            SphereRepository.read(MISSING_ID)

    def test_list_managers_raises_when_missing(self):
        with pytest.raises(NotFoundError):
            SphereRepository.list_managers(MISSING_ID)


class TestSessionRepositoryNotFound:
    def test_read_event_raises_when_session_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.read_event(MISSING_ID)

    def test_lock_raises_when_session_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.lock(MISSING_ID)

    def test_update_raises_when_session_missing(self):
        # A cover_image in the payload takes the instance-load path, which must
        # raise NotFoundError when the session is gone.
        with pytest.raises(NotFoundError):
            SessionRepository.update(MISSING_ID, {"cover_image": ""})

    def test_read_time_slot_raises_when_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.read_time_slot(MISSING_ID, MISSING_ID)

    def test_read_tag_categories_raises_when_session_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.read_tag_categories(MISSING_ID)

    def test_read_tag_categories_returns_empty_when_no_category(self, event):
        session = Session.objects.create(
            event=event,
            category=None,
            presenter=None,
            display_name="Host",
            title="No Category Session",
            slug="no-cat",
            status="pending",
            participants_limit=0,
            min_age=0,
        )

        assert SessionRepository.read_tag_categories(session.pk) == []

    def test_set_session_tracks_raises_when_session_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.set_session_tracks(MISSING_ID, [])

    def test_read_facilitators_raises_when_session_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.read_facilitators(MISSING_ID)

    def test_set_facilitators_raises_when_session_missing(self):
        with pytest.raises(NotFoundError):
            SessionRepository.set_facilitators(MISSING_ID, [])


class TestConnectedUserRepositoryNotFound:
    def test_read_all_raises_when_manager_missing(self):
        with pytest.raises(NotFoundError):
            ConnectedUserRepository.read_all("does-not-exist")

    def test_read_raises_when_user_missing(self):
        with pytest.raises(NotFoundError):
            ConnectedUserRepository.read("missing-mgr", "missing-user")

    def test_delete_raises_when_user_missing(self):
        with pytest.raises(NotFoundError):
            ConnectedUserRepository.delete("missing-mgr", "missing-user")


class TestEventRepositoryNotFound:
    def test_read_raises_when_event_missing(self):
        with pytest.raises(NotFoundError):
            EventRepository.read(MISSING_ID)

    def test_update_raises_when_event_missing(self):
        with pytest.raises(NotFoundError):
            EventRepository.update(MISSING_ID, EventUpdateData())


class TestVenueRepositoryNotFound:
    def test_update_raises_when_venue_missing(self):
        with pytest.raises(NotFoundError):
            VenueRepository().update(MISSING_ID, name="X", address="Y")

    def test_duplicate_raises_when_venue_missing(self):
        with pytest.raises(NotFoundError):
            VenueRepository().duplicate(MISSING_ID, new_name="Copy")


class TestProposalCategoryRepositoryWriteSideEffects:
    def test_set_personal_field_categories_creates_requirements(self, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = PersonalDataField.objects.create(
            event=event, name="Age", question="How old?", slug="age", order=0
        )

        ProposalCategoryRepository.set_personal_field_categories(
            field.pk, {category.pk: True}
        )

        result = ProposalCategoryRepository.get_personal_field_categories(field.pk)
        assert result == {category.pk: True}

    def test_set_session_field_categories_creates_requirements(self, event):
        category = ProposalCategory.objects.create(event=event, name="RPG", slug="rpg")
        field = SessionField.objects.create(
            event=event, name="System", question="Which system?", slug="system", order=0
        )

        ProposalCategoryRepository.set_session_field_categories(
            field.pk, {category.pk: False}
        )

        result = ProposalCategoryRepository.get_session_field_categories(field.pk)
        assert result == {category.pk: False}
