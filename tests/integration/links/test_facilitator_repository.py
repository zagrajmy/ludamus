import pytest

from ludamus.links.db.django.models import Facilitator
from ludamus.links.db.django.repositories.submissions import FacilitatorRepository
from ludamus.pacts import NotFoundError
from tests.integration.conftest import EventFactory, UserFactory


def _facilitator(event, organizer=None):
    return Facilitator.objects.create(
        event=event,
        display_name="Alice",
        slug="alice",
        accreditation_type="none",
        organizer=organizer,
    )


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
    def test_delete_stamps_the_row_and_hides_it_from_the_default_manager(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        FacilitatorRepository.delete(facilitator.pk)

        facilitator.refresh_from_db()
        assert facilitator.deleted_at is not None
        assert not Facilitator.objects.filter(pk=facilitator.pk).exists()

    def test_deleting_an_already_deleted_facilitator_is_not_found(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.delete(facilitator.pk)
        stamped_at = Facilitator.all_objects.get(pk=facilitator.pk).deleted_at

        with pytest.raises(NotFoundError):
            FacilitatorRepository.delete(facilitator.pk)

        assert Facilitator.all_objects.get(pk=facilitator.pk).deleted_at == stamped_at

    def test_a_deleted_facilitator_keeps_holding_its_slug(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.delete(facilitator.pk)

        assert FacilitatorRepository.slug_exists(event.pk, "alice") is True

    def test_a_deleted_facilitator_still_matches_by_ident(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.set_ident(facilitator.pk, "ident-1")
        FacilitatorRepository.delete(facilitator.pk)

        assert (
            FacilitatorRepository.find_id_by_ident(event.pk, "ident-1")
            == facilitator.pk
        )

    def test_restore_brings_a_deleted_facilitator_back(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)
        FacilitatorRepository.delete(facilitator.pk)

        FacilitatorRepository.restore(facilitator.pk)

        facilitator.refresh_from_db()
        assert facilitator.deleted_at is None
        assert Facilitator.objects.filter(pk=facilitator.pk).exists()

    def test_restoring_a_live_facilitator_changes_nothing(self):
        event = EventFactory.create()
        facilitator = _facilitator(event)

        FacilitatorRepository.restore(facilitator.pk)

        facilitator.refresh_from_db()
        assert facilitator.deleted_at is None


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
