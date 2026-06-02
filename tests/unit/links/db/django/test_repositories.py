from types import SimpleNamespace

from django.db import IntegrityError

from ludamus.links.db.django.repositories import is_connection_display_name_conflict


class _FakePostgresError(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("duplicate key value violates unique constraint")
        self.diag = SimpleNamespace(constraint_name=constraint_name)


def test_detects_postgres_constraint_name():
    exc = IntegrityError("duplicate key value violates unique constraint")
    exc.__cause__ = _FakePostgresError("connection_unique_display_name_per_sphere")

    assert is_connection_display_name_conflict(exc) is True


def test_detects_sqlite_constraint_message():
    exc = IntegrityError(
        "UNIQUE constraint failed: connection.sphere_id, connection.display_name"
    )

    assert is_connection_display_name_conflict(exc) is True


def test_ignores_unrelated_integrity_error():
    exc = IntegrityError("FOREIGN KEY constraint failed")

    assert is_connection_display_name_conflict(exc) is False
