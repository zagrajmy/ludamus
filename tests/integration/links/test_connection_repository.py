"""Tests for `ConnectionsRepository` secret write surface.

The encrypted blob must be writable but never readable through the
repo / DTO surface — decrypt is a forward dep owned by the
import-execution slice.
"""

import pytest
from django.db import IntegrityError

from ludamus.links.db.django.models import Connection
from ludamus.links.db.django.repositories import ConnectionsRepository
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import ConnectionDTO


class TestConnectionsRepositoryUpdate:
    def test_updates_metadata_without_overwriting_concurrent_secret_write(
        self, sphere, monkeypatch
    ):
        connection = Connection.objects.create(
            sphere=sphere, display_name="Konto", secret=b"old"
        )
        original_save = Connection.save

        def save_after_concurrent_secret_write(instance, *args, **kwargs):
            Connection.objects.filter(pk=instance.pk).update(secret=b"fresh")
            return original_save(instance, *args, **kwargs)

        monkeypatch.setattr(Connection, "save", save_after_concurrent_secret_write)

        ConnectionsRepository.update(
            sphere_id=sphere.pk, pk=connection.pk, display_name="New Account"
        )

        connection.refresh_from_db()
        assert connection.display_name == "New Account"
        assert bytes(connection.secret) == b"fresh"


class TestConnectionsRepositoryUpdateSecret:
    def test_persists_blob(self, sphere):
        connection = Connection.objects.create(sphere=sphere, display_name="Konto")

        ConnectionsRepository.update_secret(
            sphere_id=sphere.pk, pk=connection.pk, blob=b"opaque"
        )

        connection.refresh_from_db()
        assert bytes(connection.secret) == b"opaque"

    def test_overwrites_existing_blob(self, sphere):
        connection = Connection.objects.create(
            sphere=sphere, display_name="Konto", secret=b"old"
        )

        ConnectionsRepository.update_secret(
            sphere_id=sphere.pk, pk=connection.pk, blob=b"new"
        )

        connection.refresh_from_db()
        assert bytes(connection.secret) == b"new"

    def test_raises_not_found_when_missing(self, sphere):
        with pytest.raises(NotFoundError):
            ConnectionsRepository.update_secret(
                sphere_id=sphere.pk, pk=999_999, blob=b"x"
            )

    def test_raises_not_found_when_other_sphere(self, sphere, non_root_sphere):
        connection = Connection.objects.create(
            sphere=non_root_sphere, display_name="Other"
        )

        with pytest.raises(NotFoundError):
            ConnectionsRepository.update_secret(
                sphere_id=sphere.pk, pk=connection.pk, blob=b"x"
            )


class TestConnectionsRepositorySecretSurface:
    """Guard the shape of the repo's secret access surface."""

    def test_dto_does_not_carry_blob(self):
        # ConnectionDTO must never gain a secret field — listing a
        # connection never returns its bytes.
        field_names = list(ConnectionDTO.model_fields)
        assert "secret" not in field_names

    def test_repo_exposes_only_known_secret_methods(self):
        # The repo can expose `update_secret` (write) and `read_secret`
        # (read the encrypted blob — caller owns decryption). Any other
        # secret-named method needs explicit acknowledgement here.
        allowed = {"update_secret", "read_secret"}
        for name in dir(ConnectionsRepository):
            if name.startswith("_") or "secret" not in name:
                continue
            assert (
                name in allowed
            ), f"Unexpected secret accessor on repo surface: {name}"


class TestConnectionsRepositoryReraisesUnrelatedIntegrityError:
    def test_create_reraises_non_duplicate_integrity_error(self, sphere, monkeypatch):
        def raise_unrelated(*_args, **_kwargs):
            raise IntegrityError("FOREIGN KEY constraint failed")

        monkeypatch.setattr(Connection.objects, "create", raise_unrelated)

        with pytest.raises(IntegrityError):
            ConnectionsRepository.create(sphere_id=sphere.pk, display_name="Konto")

    def test_update_reraises_non_duplicate_integrity_error(self, sphere, monkeypatch):
        connection = Connection.objects.create(sphere=sphere, display_name="Konto")

        def raise_unrelated(*_args, **_kwargs):
            raise IntegrityError("FOREIGN KEY constraint failed")

        monkeypatch.setattr(Connection, "save", raise_unrelated)

        with pytest.raises(IntegrityError):
            ConnectionsRepository.update(
                sphere_id=sphere.pk, pk=connection.pk, display_name="Inne"
            )
