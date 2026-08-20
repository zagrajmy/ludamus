from types import SimpleNamespace
from unittest.mock import MagicMock

from django.db import IntegrityError

from ludamus.links.db.django.repositories import (
    delete_stored_file,
    is_connection_display_name_conflict,
)
from ludamus.links.db.django.repositories.venues import is_track_name_conflict


class TestDeleteStoredFile:
    def test_logs_and_swallows_storage_delete_errors(self, caplog):
        storage = MagicMock()
        storage.delete.side_effect = OSError("boom")
        field_file = SimpleNamespace(storage=storage)

        with caplog.at_level("WARNING", logger="ludamus.links.db.django.repositories"):
            delete_stored_file(field_file, "old.png")

        assert "Best-effort cleanup" in caplog.text


class _FakePostgresError(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("duplicate key value violates unique constraint")
        self.diag = SimpleNamespace(constraint_name=constraint_name)


def test_detects_postgres_constraint_name():
    exc = IntegrityError("duplicate key value violates unique constraint")
    exc.__cause__ = _FakePostgresError("track_unique_name_per_event")

    assert is_track_name_conflict(exc) is True


def test_detects_sqlite_column_list_message():
    # A plain unique constraint: SQLite names the columns, not the index.
    exc = IntegrityError(
        "UNIQUE constraint failed: connection.sphere_id, connection.display_name"
    )

    assert is_connection_display_name_conflict(exc) is True


def test_detects_sqlite_functional_index_message():
    exc = IntegrityError(
        "UNIQUE constraint failed: index 'track_unique_name_per_event'"
    )

    assert is_track_name_conflict(exc) is True


def test_ignores_unrelated_integrity_error():
    exc = IntegrityError("FOREIGN KEY constraint failed")

    assert is_connection_display_name_conflict(exc) is False
    assert is_track_name_conflict(exc) is False
