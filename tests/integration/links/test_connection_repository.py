"""Tests for `ConnectionsRepository` credential write surface.

The encrypted blob must be writable but never readable through the
repo / DTO surface — decrypt is a forward dep owned by the
import-execution slice.
"""

from datetime import UTC, datetime

import pytest

from ludamus.adapters.db.django.models import Connection
from ludamus.links.db.django.repositories import ConnectionsRepository
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import ConnectionDTO


class TestConnectionsRepositoryUpdate:
    def test_updates_metadata_without_overwriting_concurrent_credential_write(
        self, sphere, monkeypatch
    ):
        connection = Connection.objects.create(
            sphere=sphere,
            service="google",
            display_name="Konto",
            credentials=b"old",
            last_check_status="auth_failed",
            last_check_detail="old",
            last_check_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        fresh_check_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
        original_save = Connection.save

        def save_after_concurrent_credential_write(instance, *args, **kwargs):
            Connection.objects.filter(pk=instance.pk).update(
                credentials=b"fresh",
                last_check_status="ok",
                last_check_detail="fresh",
                last_check_at=fresh_check_at,
            )
            return original_save(instance, *args, **kwargs)

        monkeypatch.setattr(Connection, "save", save_after_concurrent_credential_write)

        ConnectionsRepository.update(
            sphere_id=sphere.pk,
            pk=connection.pk,
            data={"service": "google", "display_name": "New Account"},
        )

        connection.refresh_from_db()
        assert connection.display_name == "New Account"
        assert bytes(connection.credentials) == b"fresh"
        assert connection.last_check_status == "ok"
        assert connection.last_check_detail == "fresh"
        assert connection.last_check_at == fresh_check_at


class TestConnectionsRepositoryUpdateCredentials:
    def test_persists_blob(self, sphere):
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Konto"
        )

        ConnectionsRepository.update_credentials(
            sphere_id=sphere.pk, pk=connection.pk, blob=b"opaque"
        )

        connection.refresh_from_db()
        assert bytes(connection.credentials) == b"opaque"

    def test_overwrites_existing_blob(self, sphere):
        connection = Connection.objects.create(
            sphere=sphere, service="google", display_name="Konto", credentials=b"old"
        )

        ConnectionsRepository.update_credentials(
            sphere_id=sphere.pk, pk=connection.pk, blob=b"new"
        )

        connection.refresh_from_db()
        assert bytes(connection.credentials) == b"new"

    def test_raises_not_found_when_missing(self, sphere):
        with pytest.raises(NotFoundError):
            ConnectionsRepository.update_credentials(
                sphere_id=sphere.pk, pk=999_999, blob=b"x"
            )

    def test_raises_not_found_when_other_sphere(self, sphere, non_root_sphere):
        connection = Connection.objects.create(
            sphere=non_root_sphere, service="google", display_name="Other"
        )

        with pytest.raises(NotFoundError):
            ConnectionsRepository.update_credentials(
                sphere_id=sphere.pk, pk=connection.pk, blob=b"x"
            )


class TestConnectionsRepositorySurfaceIsWriteOnly:
    """Guard against accidental decrypt paths in this slice."""

    def test_dto_does_not_carry_blob(self):
        # ConnectionDTO must never gain a credentials field — the blob
        # is opaque and write-only at this layer.
        field_names = list(ConnectionDTO.model_fields)
        assert "credentials" not in field_names

    def test_repo_exposes_no_credentials_read_method(self):
        # No method that returns or yields the blob may exist on the
        # repo surface. This is greppable: any future "get_credentials"
        # / "read_credentials" / "credentials" accessor will trip here.
        for name in dir(ConnectionsRepository):
            if name.startswith("_"):
                continue
            assert (
                "credential" not in name or name == "update_credentials"
            ), f"Unexpected credential accessor on repo surface: {name}"
