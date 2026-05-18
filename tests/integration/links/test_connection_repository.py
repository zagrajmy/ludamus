"""Tests for `ConnectionsRepository` secret write surface.

The encrypted blob must be writable but never readable through the
repo / DTO surface — decrypt is a forward dep owned by the
import-execution slice.
"""

import pytest

from ludamus.adapters.db.django.models import Connection
from ludamus.links.db.django.repositories import ConnectionsRepository
from ludamus.pacts import NotFoundError
from ludamus.pacts.multiverse import ConnectionDTO


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


class TestConnectionsRepositorySurfaceIsWriteOnly:
    """Guard against accidental decrypt paths in this slice."""

    def test_dto_does_not_carry_blob(self):
        # ConnectionDTO must never gain a secret field — the blob is
        # opaque and write-only at this layer.
        field_names = list(ConnectionDTO.model_fields)
        assert "secret" not in field_names

    def test_repo_exposes_no_secret_read_method(self):
        # No method that returns or yields the blob may exist on the
        # repo surface. This is greppable: any future "get_secret" /
        # "read_secret" / "secret" accessor will trip here.
        for name in dir(ConnectionsRepository):
            if name.startswith("_"):
                continue
            assert (
                "secret" not in name or name == "update_secret"
            ), f"Unexpected secret accessor on repo surface: {name}"
