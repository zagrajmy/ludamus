"""Integration tests for `ImportLogEntryRepository`."""

from __future__ import annotations

import pytest

from ludamus.adapters.db.django.models import Connection, EventIntegration, Session
from ludamus.links.db.django.repositories import ImportLogEntryRepository
from ludamus.pacts import NotFoundError, SessionStatus
from ludamus.pacts.chronology import IntegrationImplementationId, IntegrationKind
from ludamus.pacts.submissions import ImportLogEntryCreateData, ImportLogStatus
from tests.integration.conftest import EventFactory, SphereFactory

_INTEGRATION_COUNTER = {"n": 0}


def _integration(*, event=None, sphere=None) -> EventIntegration:
    sphere = sphere or SphereFactory.create()
    event = event or EventFactory.create(sphere=sphere)
    _INTEGRATION_COUNTER["n"] += 1
    suffix = _INTEGRATION_COUNTER["n"]
    connection = Connection.objects.create(
        sphere=sphere, display_name=f"API key {suffix}"
    )
    return EventIntegration.objects.create(
        event=event,
        kind=IntegrationKind.IMPORT.value,
        implementation=IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER.value,
        connection=connection,
        display_name=f"Puller {suffix}",
        config_json="{}",
    )


def _session(sphere) -> Session:
    return Session.objects.create(
        event=EventFactory.create(sphere=sphere),
        sphere=sphere,
        title="Talk",
        slug="talk",
        status=SessionStatus.PENDING.value,
        participants_limit=0,
    )


@pytest.mark.django_db
class TestImportLogEntryRepositoryUpsert:
    def test_re_upsert_overwrites_the_same_row_in_place(self):
        integration = _integration()
        first = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SKIPPED,
                reason="initial",
                response_json="{}",
            )
        )

        second = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SUCCESS,
                reason="",
                response_json="{}",
            )
        )

        # Same DB row, updated in place.
        assert second.pk == first.pk
        assert (
            ImportLogEntryRepository.list_for_integration(integration.pk)[0].status
            == ImportLogStatus.SUCCESS
        )

    def test_persists_a_skipped_entry(self):
        integration = _integration()
        row_index = 2

        dto = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=row_index,
                status=ImportLogStatus.SKIPPED,
                reason="bad",
                response_json='{"Title": "Talk"}',
                title="Talk",
            )
        )

        assert dto.integration_id == integration.pk
        assert dto.status == ImportLogStatus.SKIPPED
        assert dto.row_index == row_index
        assert dto.reason == "bad"
        assert dto.title == "Talk"
        assert dto.session_id is None

    def test_persists_a_success_entry_linked_to_a_session(self, sphere):
        integration = _integration(sphere=sphere)
        session = _session(sphere)

        dto = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
                title="Talk",
                session_id=session.pk,
            )
        )

        assert dto.status == ImportLogStatus.SUCCESS
        assert dto.session_id == session.pk


@pytest.mark.django_db
class TestImportLogEntryRepositoryListForIntegration:
    def test_returns_entries_in_reverse_chronological_order(self):
        integration = _integration()
        first = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SKIPPED,
                reason="a",
                response_json="{}",
            )
        )
        second = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=1,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
            )
        )

        entries = ImportLogEntryRepository.list_for_integration(integration.pk)

        assert [e.pk for e in entries] == [second.pk, first.pk]

    def test_filters_by_status(self):
        integration = _integration()
        ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SKIPPED,
                response_json="{}",
            )
        )
        kept = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=1,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
            )
        )

        successes = ImportLogEntryRepository.list_for_integration(
            integration.pk, status=ImportLogStatus.SUCCESS
        )

        assert [e.pk for e in successes] == [kept.pk]

    def test_filters_by_title_or_display_name_search(self):
        integration = _integration()
        match_title = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
                title="Dragons of Despair",
            )
        )
        match_display = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=1,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
                title="Other",
                display_name="DragonMaster",
            )
        )
        ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=2,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
                title="Unrelated",
            )
        )

        hits = ImportLogEntryRepository.list_for_integration(
            integration.pk, search="dragon"
        )

        assert {e.pk for e in hits} == {match_title.pk, match_display.pk}

    def test_scopes_to_integration(self):
        sphere = SphereFactory.create()
        event = EventFactory.create(sphere=sphere)
        first = _integration(event=event, sphere=sphere)
        other = _integration(event=event, sphere=sphere)
        ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=other.pk,
                row_index=0,
                status=ImportLogStatus.SKIPPED,
                response_json="{}",
            )
        )

        assert ImportLogEntryRepository.list_for_integration(first.pk) == []


@pytest.mark.django_db
class TestImportLogEntryRepositoryForSession:
    def test_returns_the_entry_linked_to_the_session(self, sphere):
        integration = _integration(sphere=sphere)
        session = _session(sphere)
        entry = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=0,
                status=ImportLogStatus.SUCCESS,
                response_json="{}",
                session_id=session.pk,
            )
        )

        dto = ImportLogEntryRepository.for_session(session.pk)

        assert dto is not None
        assert dto.pk == entry.pk

    def test_returns_none_when_no_entry_links_to_the_session(self, sphere):
        session = _session(sphere)

        assert ImportLogEntryRepository.for_session(session.pk) is None


@pytest.mark.django_db
class TestImportLogEntryRepositoryRead:
    def test_returns_the_entry(self):
        integration = _integration()
        row_index = 3
        created = ImportLogEntryRepository.upsert(
            ImportLogEntryCreateData(
                integration_id=integration.pk,
                row_index=row_index,
                status=ImportLogStatus.SKIPPED,
                response_json="{}",
            )
        )

        dto = ImportLogEntryRepository.read(created.pk)

        assert dto.pk == created.pk
        assert dto.row_index == row_index

    def test_raises_when_missing(self):
        with pytest.raises(NotFoundError):
            ImportLogEntryRepository.read(99999)
