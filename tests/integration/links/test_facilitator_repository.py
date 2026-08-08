import pytest

from ludamus.links.db.django.models import Facilitator
from ludamus.links.db.django.repositories import SessionRepository
from ludamus.links.db.django.repositories.submissions import FacilitatorRepository
from ludamus.pacts import NotFoundError
from tests.integration.conftest import (
    EventFactory,
    ProposalCategoryFactory,
    SessionFactory,
    UserFactory,
)


def _facilitator(event, organizer=None):
    return Facilitator.objects.create(
        event=event,
        display_name="Alice",
        slug="alice",
        accreditation_type="none",
        organizer=organizer,
    )


def _session(event):
    return SessionFactory(category=ProposalCategoryFactory(event=event), event=event)


class TestFacilitatorRepositoryClaim:
    def test_claims_a_free_facilitator(self):
        event = EventFactory.create()
        organizer = UserFactory(username="one", email="one@example.com")
        facilitator = _facilitator(event)

        claimed = FacilitatorRepository.claim(facilitator.pk, organizer.pk)

        facilitator.refresh_from_db()
        assert claimed is True
        assert facilitator.organizer_id == organizer.pk

    def test_a_second_claim_on_a_held_facilitator_loses(self):
        event = EventFactory.create()
        winner = UserFactory(username="one", email="one@example.com")
        loser = UserFactory(username="two", email="two@example.com")
        facilitator = _facilitator(event)
        FacilitatorRepository.claim(facilitator.pk, winner.pk)

        claimed = FacilitatorRepository.claim(facilitator.pk, loser.pk)

        facilitator.refresh_from_db()
        assert claimed is False
        assert facilitator.organizer_id == winner.pk


class TestFacilitatorRepositoryRelease:
    def test_the_holder_releases_it(self):
        event = EventFactory.create()
        organizer = UserFactory(username="one", email="one@example.com")
        facilitator = _facilitator(event, organizer)

        released = FacilitatorRepository.release(
            facilitator.pk, organizer_id=organizer.pk
        )

        facilitator.refresh_from_db()
        assert released is True
        assert facilitator.organizer_id is None

    def test_someone_else_cannot_release_it(self):
        event = EventFactory.create()
        organizer = UserFactory(username="one", email="one@example.com")
        other = UserFactory(username="two", email="two@example.com")
        facilitator = _facilitator(event, organizer)

        released = FacilitatorRepository.release(facilitator.pk, organizer_id=other.pk)

        facilitator.refresh_from_db()
        assert released is False
        assert facilitator.organizer_id == organizer.pk

    def test_no_organizer_id_releases_whoever_holds_it(self):
        event = EventFactory.create()
        organizer = UserFactory(username="one", email="one@example.com")
        facilitator = _facilitator(event, organizer)

        released = FacilitatorRepository.release(facilitator.pk, organizer_id=None)

        facilitator.refresh_from_db()
        assert released is True
        assert facilitator.organizer_id is None

    def test_releasing_a_free_facilitator_reports_no_change(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        released = FacilitatorRepository.release(facilitator.pk, organizer_id=None)

        assert released is False


class TestFacilitatorRepositorySoftDelete:
    def test_soft_delete_stamps_the_row_and_hides_it_from_the_default_manager(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        FacilitatorRepository.soft_delete(facilitator.pk)

        facilitator.refresh_from_db()
        assert facilitator.deleted_at is not None
        assert not Facilitator.objects.filter(pk=facilitator.pk).exists()

    def test_soft_deleting_an_already_deleted_facilitator_is_not_found(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.soft_delete(facilitator.pk)
        stamped_at = Facilitator.all_objects.get(pk=facilitator.pk).deleted_at

        with pytest.raises(NotFoundError):
            FacilitatorRepository.soft_delete(facilitator.pk)

        assert Facilitator.all_objects.get(pk=facilitator.pk).deleted_at == stamped_at

    def test_delete_destroys_the_row(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        FacilitatorRepository.delete(facilitator.pk)

        assert not Facilitator.all_objects.filter(pk=facilitator.pk).exists()

    def test_a_deleted_facilitator_keeps_holding_its_slug(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.soft_delete(facilitator.pk)

        assert FacilitatorRepository.slug_exists(event.pk, "alice") is True

    def test_a_deleted_facilitator_still_matches_by_ident(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.set_ident(facilitator.pk, "ident-1")
        FacilitatorRepository.soft_delete(facilitator.pk)

        found = FacilitatorRepository.find_by_ident(event.pk, "ident-1")

        assert found is not None
        assert found.pk == facilitator.pk
        assert found.deleted_at is not None

    def test_find_by_ident_without_a_match_is_none(self):
        event = EventFactory.create()

        assert FacilitatorRepository.find_by_ident(event.pk, "nobody") is None

    def test_restore_brings_a_deleted_facilitator_back(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.soft_delete(facilitator.pk)

        FacilitatorRepository.restore(facilitator.pk)

        facilitator.refresh_from_db()
        assert facilitator.deleted_at is None
        assert Facilitator.objects.filter(pk=facilitator.pk).exists()

    def test_restoring_a_live_facilitator_is_not_found(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        with pytest.raises(NotFoundError):
            FacilitatorRepository.restore(facilitator.pk)

    def test_read_by_event_and_slug_leaves_out_a_deleted_facilitator(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.soft_delete(facilitator.pk)

        with pytest.raises(NotFoundError):
            FacilitatorRepository.read_by_event_and_slug(event.pk, "alice")

    def test_read_including_deleted_reaches_a_deleted_facilitator(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.soft_delete(facilitator.pk)

        found = FacilitatorRepository.read_including_deleted(event.pk, "alice")

        assert found.pk == facilitator.pk
        assert found.deleted_at is not None

    def test_read_including_deleted_without_a_row_is_not_found(self):
        event = EventFactory.create()

        with pytest.raises(NotFoundError):
            FacilitatorRepository.read_including_deleted(event.pk, "nobody")


class TestFacilitatorRepositoryLock:
    def test_a_dead_row_locks_too(self):
        # The delete path locks whatever `read_by_event_and_slug` returned, so
        # the lock never gets to decide a row is out of scope.
        event = EventFactory.create()
        facilitator = _facilitator(event)
        facilitator.soft_delete()

        assert FacilitatorRepository.lock(facilitator.pk) is None

    def test_a_missing_row_is_not_an_error(self):
        assert FacilitatorRepository.lock(0) is None


class TestSessionFacilitatorLinkRejectsDeleted:
    # The other ordering of the deletion race: the delete wins the lock, so the
    # assignment must find the row gone rather than write a link onto it.
    def test_set_facilitators_refuses_a_deleted_facilitator(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        session = _session(event)
        facilitator.soft_delete()

        with pytest.raises(NotFoundError):
            SessionRepository.set_facilitators(session.pk, [facilitator.pk])

        assert not session.facilitators.exists()


class TestFacilitatorRepositoryHasSessions:
    def test_a_facilitator_without_sessions_has_none(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        assert FacilitatorRepository.has_sessions(facilitator.pk) is False

    def test_a_facilitator_running_a_session_has_sessions(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        _session(event).facilitators.add(facilitator)

        assert FacilitatorRepository.has_sessions(facilitator.pk) is True

    def test_a_deleted_session_counts_too(self):
        # It is restorable, and a restore that brought back a session with a
        # deleted facilitator would drop the byline.
        event = EventFactory.create()
        facilitator = _facilitator(event)
        session = _session(event)
        session.facilitators.add(facilitator)
        session.soft_delete()

        assert FacilitatorRepository.has_sessions(facilitator.pk) is True


class TestFacilitatorRepositorySessionCount:
    def test_the_list_and_the_merge_basket_agree(self):
        # Both feed FacilitatorListItemDTO.session_count; an organizer picking a
        # merge survivor must not see a different number than the list showed.
        event = EventFactory.create()
        facilitator = _facilitator(event)
        _session(event).facilitators.add(facilitator)
        deleted_session = _session(event)
        deleted_session.facilitators.add(facilitator)
        deleted_session.soft_delete()

        listed = FacilitatorRepository.list_by_event(event.pk)
        basket = FacilitatorRepository.list_by_slugs(event.pk, [facilitator.slug])

        assert [f.session_count for f in listed] == [1]
        assert [f.session_count for f in basket] == [1]


class TestFacilitatorRepositoryRead:
    def test_read_carries_the_organizer_name(self):
        event = EventFactory.create()
        organizer = UserFactory(
            username="one", email="one@example.com", name="Ola Organizer"
        )
        facilitator = _facilitator(event, organizer)

        dto = FacilitatorRepository.read_by_event_and_slug(event.pk, facilitator.slug)

        assert dto.organizer_id == organizer.pk
        assert dto.organizer_name == "Ola Organizer"

    def test_read_leaves_the_organizer_name_empty_when_nobody_holds_it(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        dto = FacilitatorRepository.read_by_event_and_slug(event.pk, facilitator.slug)

        assert dto.organizer_id is None
        assert dto.organizer_name is None
