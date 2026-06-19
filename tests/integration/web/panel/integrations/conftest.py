"""Fixtures shared across event-integration view tests."""

from __future__ import annotations

import json

import pytest
from django.conf import settings

from ludamus.adapters.db.django.models import Connection
from ludamus.links.encryption import FernetEncryptor


@pytest.fixture(name="connection")
def connection_fixture(sphere):
    return Connection.objects.create(sphere=sphere, display_name="API Key A")


@pytest.fixture(name="connection_with_secret")
def connection_with_secret_fixture(sphere):
    # The check path decrypts this blob and hands the plaintext to the real
    # GoogleDocsProposalImporter. Tests mock google.auth, so the content only
    # needs to be valid JSON — the importer json.loads() it before building
    # service-account credentials.
    blob = FernetEncryptor(settings.CREDENTIALS_ENCRYPTION_KEY).encrypt(
        json.dumps({"type": "service_account"}).encode()
    )
    return Connection.objects.create(
        sphere=sphere, display_name="API Key A", secret=blob
    )
