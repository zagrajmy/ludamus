import logging

import pytest
from pydantic import BaseModel

from ludamus.mills.integrations import (
    EventIntegrationsService,
    IntegrationImplementationNotFoundError,
    IntegrationImplementations,
)
from ludamus.pacts import MembershipAPIError, NotFoundError
from ludamus.pacts.chronology import (
    CheckOutcome,
    CheckResult,
    EventIntegrationCreateData,
    EventIntegrationDTO,
    EventIntegrationUpdateData,
    IntegrationCheckRequest,
    IntegrationImplementationId,
    IntegrationKind,
    SourceQuestion,
)
from ludamus.pacts.multiverse import DecryptionError
from ludamus.pacts.submissions import ImportRow, ImportSettings, QuestionTarget
from tests.unit.factories import FakeTransaction

SPHERE = 1
OTHER_SPHERE = 9
EVENT = 2
OTHER_EVENT = 8
PK = 3
CONNECTION = 4
OTHER_CONNECTION = 5
EMPTY_CONNECTION = 6
_IMPL = IntegrationImplementationId.GOOGLE_PROPOSAL_PULLER
_TICKET_IMPL = IntegrationImplementationId.SKLEP_KAPITULARZ
_EXPORT_IMPL = IntegrationImplementationId.KONWENCIK_SHEET_PUSHER
_MEMBERSHIP_COUNT = 5
_EMAIL = "player@example.com"
_HEADER_ROW = 3
_QUESTIONS = (SourceQuestion(title="Tytuł"), SourceQuestion(title="Opis"))


class _StrictConfig(BaseModel):
    endpoint: str


class _ImportImpl:
    kind = IntegrationKind.IMPORT
    config_model = _StrictConfig

    def __init__(self, *, questions=_QUESTIONS, headers=(), responses=()):
        self._questions = list(questions)
        self._headers = list(headers)
        self._responses = list(responses)

    @staticmethod
    def check(secret, config):
        return CheckResult(
            outcome=CheckOutcome.OK, hint=f"{secret!r} {config.endpoint}"
        )

    def fetch_questions(self, *, secret, config, header_row):
        return [
            q.model_copy(update={"title": f"{q.title}@{header_row}"})
            for q in self._questions
        ]

    def fetch_headers(self, *, secret, config, header_row):
        return self._headers

    def fetch_responses(self, *, secret, config, header_row):
        return self._responses


class _MembershipConfig(BaseModel):
    base_url: str


class _TicketingImpl:
    kind = IntegrationKind.TICKETING
    config_model = _MembershipConfig

    def __init__(self, membership_count=_MEMBERSHIP_COUNT):
        self._membership_count = membership_count

    def fetch_membership_count(self, *, secret, config, user_email):
        return self._membership_count


class _ExportImpl:
    kind = IntegrationKind.EXPORT
    config_model = _StrictConfig


def _row(**overrides) -> EventIntegrationDTO:
    defaults = {
        "pk": PK,
        "event_id": EVENT,
        "kind": IntegrationKind.IMPORT,
        "implementation": _IMPL,
        "connection_id": CONNECTION,
        "connection_display_name": "Service account",
        "display_name": "Proposals sheet",
        "config_json": '{"endpoint": "x"}',
        "settings_json": "{}",
    }
    return EventIntegrationDTO(**(defaults | overrides))


def _ticketing_row(
    pk=1, config_json='{"base_url": "https://shop.example.com"}', **over
):
    return _row(
        pk=pk,
        kind=IntegrationKind.TICKETING,
        implementation=_TICKET_IMPL,
        config_json=config_json,
        **over,
    )


class FakeIntegrations:
    def __init__(self, rows: list[EventIntegrationDTO]) -> None:
        self.rows = {row.pk: row for row in rows}

    def list_for_event(self, event_id, kind=None):
        return [
            row
            for row in self.rows.values()
            if row.event_id == event_id and (kind is None or row.kind == kind)
        ]

    def get(self, event_id, pk):
        row = self.rows.get(pk)
        if row is None or row.event_id != event_id:
            raise NotFoundError
        return row

    def create(self, event_id, data):
        row = _row(
            pk=max(self.rows, default=0) + 1,
            event_id=event_id,
            connection_display_name="",
            **data,
        )
        self.rows[row.pk] = row
        return row

    def update(self, event_id, pk, data):
        self.rows[pk] = self.get(event_id, pk).model_copy(update=dict(data))
        return self.rows[pk]

    def delete(self, event_id, pk):
        self.get(event_id, pk)
        del self.rows[pk]

    def update_questions_snapshot(self, *, event_id, pk, questions_snapshot_json):
        self._patch(event_id, pk, questions_snapshot_json=questions_snapshot_json)

    def update_settings(self, *, event_id, pk, settings_json):
        self._patch(event_id, pk, settings_json=settings_json)

    def _patch(self, event_id, pk, **fields):
        self.rows[pk] = self.get(event_id, pk).model_copy(update=fields)


class FakeConnections:
    def __init__(self, secrets: dict[tuple[int, int], bytes]) -> None:
        self._secrets = secrets

    def get(self, sphere_id, pk):
        self.read_secret(sphere_id, pk)
        return object()

    def read_secret(self, sphere_id, pk):
        if (sphere_id, pk) not in self._secrets:
            raise NotFoundError
        return self._secrets[sphere_id, pk]


class FakeDecryptor:
    def __init__(self, *, broken: bool = False) -> None:
        self._broken = broken

    def decrypt(self, blob: bytes) -> bytes:
        if self._broken:
            raise DecryptionError
        return b"plain:" + blob


def _service(
    *, rows=(), imports=None, ticketing=None, exports=None, broken_decryptor=False
) -> tuple[EventIntegrationsService, FakeIntegrations]:
    integrations = FakeIntegrations(list(rows))
    service = EventIntegrationsService(
        transaction=FakeTransaction(),
        integrations=integrations,
        connections=FakeConnections(
            {
                (SPHERE, CONNECTION): b"blob",
                (SPHERE, OTHER_CONNECTION): b"other",
                (SPHERE, EMPTY_CONNECTION): b"",
            }
        ),
        decryptor=FakeDecryptor(broken=broken_decryptor),
        implementations=IntegrationImplementations(
            imports=imports if imports is not None else {_IMPL: _ImportImpl()},
            ticketing=ticketing or {},
            exports=exports or {},
        ),
    )
    return service, integrations


def _settings(integrations: FakeIntegrations, pk: int = PK) -> ImportSettings:
    return ImportSettings.model_validate_json(integrations.rows[pk].settings_json)


class TestRegistry:
    def test_implementations_are_listed_per_kind_or_all_at_once(self):
        service, _ = _service(
            ticketing={_TICKET_IMPL: _TicketingImpl()},
            exports={_EXPORT_IMPL: _ExportImpl()},
        )

        assert set(service.list_implementations(IntegrationKind.EXPORT)) == {
            _EXPORT_IMPL
        }
        assert set(service.list_all_implementations()) == {
            _IMPL,
            _TICKET_IMPL,
            _EXPORT_IMPL,
        }


class TestCrud:
    def test_rows_are_listed_by_event_and_kind(self):
        service, _ = _service(
            rows=[_row(pk=1), _ticketing_row(pk=2), _row(pk=3, event_id=OTHER_EVENT)]
        )

        assert [r.pk for r in service.list_for_event(EVENT)] == [1, 2]
        assert [
            r.pk for r in service.list_for_event(EVENT, IntegrationKind.IMPORT)
        ] == [1]
        assert service.get(EVENT, 1).pk == 1
        with pytest.raises(NotFoundError):
            service.get(EVENT, 3)

    def test_create_stores_the_row(self):
        service, integrations = _service()

        created = service.create(
            SPHERE,
            EVENT,
            EventIntegrationCreateData(
                kind=IntegrationKind.IMPORT,
                implementation=_IMPL,
                connection_id=CONNECTION,
                display_name="Sheet",
                config_json='{"endpoint": "x"}',
            ),
        )

        assert integrations.rows[created.pk].display_name == "Sheet"

    @pytest.mark.parametrize(
        ("implementation", "kind"),
        ((_TICKET_IMPL, IntegrationKind.TICKETING), (_IMPL, IntegrationKind.EXPORT)),
    )
    def test_create_rejects_an_unknown_or_mismatched_implementation(
        self, implementation, kind
    ):
        service, integrations = _service()

        with pytest.raises(IntegrationImplementationNotFoundError):
            service.create(
                SPHERE,
                EVENT,
                EventIntegrationCreateData(
                    kind=kind,
                    implementation=implementation,
                    connection_id=CONNECTION,
                    display_name="Sheet",
                    config_json="{}",
                ),
            )

        assert integrations.rows == {}

    def test_create_rejects_a_connection_of_another_sphere(self):
        service, integrations = _service()

        with pytest.raises(NotFoundError):
            service.create(
                OTHER_SPHERE,
                EVENT,
                EventIntegrationCreateData(
                    kind=IntegrationKind.IMPORT,
                    implementation=_IMPL,
                    connection_id=CONNECTION,
                    display_name="Sheet",
                    config_json="{}",
                ),
            )

        assert integrations.rows == {}

    def test_update_replaces_name_connection_and_config(self):
        service, integrations = _service(rows=[_row()])

        service.update(
            SPHERE,
            EVENT,
            PK,
            EventIntegrationUpdateData(
                display_name="Renamed",
                connection_id=OTHER_CONNECTION,
                config_json='{"endpoint": "y"}',
            ),
        )

        row = integrations.rows[PK]
        assert (row.display_name, row.connection_id) == ("Renamed", OTHER_CONNECTION)

    def test_update_rejects_a_connection_of_another_sphere(self):
        service, integrations = _service(rows=[_row()])

        with pytest.raises(NotFoundError):
            service.update(
                OTHER_SPHERE,
                EVENT,
                PK,
                EventIntegrationUpdateData(
                    display_name="Renamed", connection_id=CONNECTION, config_json="{}"
                ),
            )

        assert integrations.rows[PK].display_name == "Proposals sheet"

    def test_delete_removes_the_row(self):
        service, integrations = _service(rows=[_row()])

        service.delete(EVENT, PK)

        assert integrations.rows == {}

    def test_save_settings_stores_the_blob(self):
        service, integrations = _service(rows=[_row()])

        service.save_settings(event_id=EVENT, pk=PK, settings_json='{"header_row": 2}')

        assert _settings(integrations).header_row == _HEADER_ROW - 1


class TestFetch:
    def test_questions_headers_and_responses_come_from_the_bound_import(self):
        response = ImportRow({"Tytuł": "Dracula"})
        service, _ = _service(
            rows=[_row(settings_json='{"header_row": 3}')],
            imports={_IMPL: _ImportImpl(headers=["A"], responses=[response])},
        )

        questions = service.fetch_questions(sphere_id=SPHERE, event_id=EVENT, pk=PK)

        assert [q.title for q in questions] == ["Tytuł@3", "Opis@3"]
        assert service.fetch_headers(sphere_id=SPHERE, event_id=EVENT, pk=PK) == ["A"]
        assert service.fetch_responses(sphere_id=SPHERE, event_id=EVENT, pk=PK) == [
            response
        ]

    def test_a_row_that_is_not_an_import_fetches_nothing(self):
        service, _ = _service(rows=[_ticketing_row(pk=PK)])

        assert service.fetch_questions(sphere_id=SPHERE, event_id=EVENT, pk=PK) == []
        assert service.fetch_headers(sphere_id=SPHERE, event_id=EVENT, pk=PK) == []
        assert service.fetch_responses(sphere_id=SPHERE, event_id=EVENT, pk=PK) == []

    def test_a_connection_without_a_secret_binds_with_an_empty_one(self):
        service, _ = _service(rows=[_row(connection_id=EMPTY_CONNECTION)])

        questions = service.fetch_questions(sphere_id=SPHERE, event_id=EVENT, pk=PK)

        assert len(questions) == len(_QUESTIONS)


class TestSnapshot:
    def test_cached_questions_are_read_from_the_snapshot(self):
        service, _ = _service(
            rows=[_row(questions_snapshot_json='[{"title": "Tytuł"}]')]
        )

        assert service.get_cached_questions(EVENT, PK) == [
            SourceQuestion(title="Tytuł")
        ]

    def test_a_malformed_snapshot_reads_as_no_questions(self):
        service, _ = _service(rows=[_row(questions_snapshot_json='[{"nope": 1}]')])

        assert service.get_cached_questions(EVENT, PK) == []

    def test_populate_writes_the_snapshot_and_fresh_headers(self):
        service, integrations = _service(
            rows=[_row(settings_json='{"sheet_headers": ["Old"]}')],
            imports={_IMPL: _ImportImpl(headers=["Sygnatura czasowa", "Tytuł"])},
        )

        questions = service.populate_questions_snapshot(
            sphere_id=SPHERE, event_id=EVENT, pk=PK
        )

        assert service.get_cached_questions(EVENT, PK) == questions
        assert _settings(integrations).sheet_headers == ["Sygnatura czasowa", "Tytuł"]

    def test_populate_keeps_cached_headers_when_the_fetch_fails(self):
        # A transient Sheets failure yields []; wiping the cache would empty the
        # unique-key select the operator already configured against.
        service, integrations = _service(
            rows=[_row(settings_json='{"sheet_headers": ["Sygnatura czasowa"]}')],
            imports={_IMPL: _ImportImpl(headers=[])},
        )

        service.populate_questions_snapshot(sphere_id=SPHERE, event_id=EVENT, pk=PK)

        assert _settings(integrations).sheet_headers == ["Sygnatura czasowa"]

    def test_refetch_drops_vanished_questions_and_every_confirmation(self):
        before = ImportSettings(
            questions={
                "Tytuł@1": QuestionTarget(to="session.title", confirmed=True),
                "Gone": QuestionTarget(to="session.description", confirmed=True),
            },
            sheet_headers=["Tytuł"],
        )
        service, integrations = _service(
            rows=[_row(settings_json=before.model_dump_json())],
            imports={_IMPL: _ImportImpl(headers=["Tytuł", "Opis"])},
        )

        questions = service.refetch_questions(sphere_id=SPHERE, event_id=EVENT, pk=PK)

        after = _settings(integrations)
        assert [q.title for q in questions] == ["Tytuł@1", "Opis@1"]
        assert after.questions == {
            "Tytuł@1": QuestionTarget(to="session.title", confirmed=False)
        }
        assert after.sheet_headers == ["Tytuł", "Opis"]

    def test_import_missing_counts_questions_not_yet_mapped(self):
        before = ImportSettings(
            questions={"Tytuł@1": QuestionTarget(to="session.title", confirmed=True)}
        )
        service, integrations = _service(
            rows=[_row(settings_json=before.model_dump_json())]
        )

        questions, missing = service.import_missing_questions(
            sphere_id=SPHERE, event_id=EVENT, pk=PK
        )

        assert len(questions) == len(_QUESTIONS)
        assert missing == 1
        assert _settings(integrations).questions["Tytuł@1"].confirmed is True


def _check_request(**overrides) -> IntegrationCheckRequest:
    defaults = {
        "sphere_id": SPHERE,
        "implementation": _IMPL,
        "connection_id": CONNECTION,
        "config_json": '{"endpoint": "x"}',
    }
    return IntegrationCheckRequest(**(defaults | overrides))


class TestCheck:
    def test_probes_the_implementation_with_the_decrypted_secret(self):
        service, _ = _service()

        result = service.check(_check_request())

        assert result == CheckResult(outcome=CheckOutcome.OK, hint="b'plain:blob' x")

    def test_a_secret_less_connection_probes_with_an_empty_secret(self):
        service, _ = _service()

        result = service.check(_check_request(connection_id=EMPTY_CONNECTION))

        assert result.hint == "b'' x"

    def test_an_unknown_implementation_is_reported(self):
        service, _ = _service()

        result = service.check(_check_request(implementation=_TICKET_IMPL))

        assert result.outcome is CheckOutcome.NOT_FOUND
        assert "Unknown implementation" in result.hint

    def test_an_invalid_config_is_reported(self):
        service, _ = _service()

        result = service.check(_check_request(config_json='{"endpoint": 1}'))

        assert result.outcome is CheckOutcome.NOT_FOUND
        assert result.hint.startswith("Invalid config")

    def test_a_missing_connection_is_reported(self):
        service, _ = _service()

        result = service.check(_check_request(sphere_id=OTHER_SPHERE))

        assert result == CheckResult(
            outcome=CheckOutcome.NOT_FOUND, hint="Connection not found."
        )


def _ticketing_service(rows, **kwargs):
    service, integrations = _service(
        rows=rows, ticketing={_TICKET_IMPL: _TicketingImpl()}, **kwargs
    )
    return service, integrations


class TestTicketApi:
    def test_resolve_falls_back_to_the_next_usable_integration(self):
        # First usable row wins; a broken one must not take the event down.
        service, _ = _ticketing_service(
            [_ticketing_row(pk=1, config_json='{"base_url": 42}'), _ticketing_row(pk=2)]
        )

        client = service.resolve(event_id=EVENT, sphere_id=SPHERE)

        assert client.fetch_membership_count(_EMAIL) == _MEMBERSHIP_COUNT

    def test_resolve_is_answered_once_per_event(self):
        service, integrations = _ticketing_service([_ticketing_row()])

        first = service.resolve(event_id=EVENT, sphere_id=SPHERE)
        integrations.rows.clear()

        assert service.resolve(event_id=EVENT, sphere_id=SPHERE) is first

    def test_an_event_without_ticketing_reads_as_unreachable(self):
        service, _ = _service(rows=[_row()])

        client = service.resolve(event_id=EVENT, sphere_id=SPHERE)

        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count(_EMAIL)

    def test_a_row_whose_implementation_is_not_shipped_is_skipped(self):
        service, _ = _service(rows=[_ticketing_row()])

        client = service.resolve(event_id=EVENT, sphere_id=SPHERE)

        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count(_EMAIL)

    @pytest.mark.parametrize(
        ("row", "broken", "message"),
        (
            (_ticketing_row(connection_id=99), False, "missing connection"),
            (_ticketing_row(connection_id=EMPTY_CONNECTION), False, "no secret"),
            (_ticketing_row(), True, "does not decrypt"),
        ),
    )
    def test_an_unusable_secret_is_logged_and_the_row_skipped(
        self, caplog, row, broken, message
    ):
        # A rotated key, a deleted connection or an empty one must skip the
        # row, not 500 the enrollment page it was resolved for.
        service, _ = _ticketing_service([row], broken_decryptor=broken)

        with caplog.at_level(logging.WARNING):
            client = service.resolve(event_id=EVENT, sphere_id=SPHERE)

        assert message in caplog.text
        with pytest.raises(MembershipAPIError):
            client.fetch_membership_count(_EMAIL)
