from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from ludamus.pacts.images import (
    UPLOAD_SUFFIXES,
    StoredFile,
    original_filename,
    stored_file,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

logger = logging.getLogger(__name__)

_WIZARD_COVER_KEY = "cover_image_temp"
_WIZARD_COVER_NAME_KEY = "cover_image_temp_name"


def _discard_stored_cover(path: str) -> None:
    # Deleting the stashed cover is pure cleanup: the bytes we need are already
    # read by the caller. A storage backend that refuses the delete (e.g. a
    # service account without storage.objects.delete) must not fail the wizard
    # submission, so we swallow the error and leak the temp object instead. A
    # bucket lifecycle rule on the propose-wizard/ prefix reclaims the leak.
    try:
        default_storage.delete(path)
    except Exception:
        logger.warning("Failed to delete stashed wizard cover %s", path, exc_info=True)


def delete_wizard_cover(wizard: dict[str, Any]) -> None:
    if path := wizard.get(_WIZARD_COVER_KEY):
        _discard_stored_cover(path)
    wizard.pop(_WIZARD_COVER_KEY, None)
    wizard.pop(_WIZARD_COVER_NAME_KEY, None)


def stash_wizard_cover(
    wizard: dict[str, Any], uploaded_file: UploadedFile[bytes]
) -> None:
    delete_wizard_cover(wizard)
    name = original_filename(getattr(uploaded_file, "name", "") or "cover")
    suffix = PurePosixPath(name).suffix.lower()
    wizard[_WIZARD_COVER_KEY] = default_storage.save(
        f"propose-wizard/{uuid4().hex}{suffix if suffix in UPLOAD_SUFFIXES else ''}",
        uploaded_file,
    )
    wizard[_WIZARD_COVER_NAME_KEY] = name


def wizard_cover_initial(wizard: dict[str, Any]) -> StoredFile | None:
    if (path := wizard.get(_WIZARD_COVER_KEY)) and default_storage.exists(path):
        return stored_file(
            default_storage.url(path), wizard.get(_WIZARD_COVER_NAME_KEY, "")
        )
    return None


def pop_wizard_cover(wizard: dict[str, Any]) -> ContentFile[bytes] | None:
    path = wizard.pop(_WIZARD_COVER_KEY, None)
    name = wizard.pop(_WIZARD_COVER_NAME_KEY, None) or "cover"
    if not path or not default_storage.exists(path):
        return None
    with default_storage.open(path) as stored:
        data = stored.read()
    _discard_stored_cover(path)
    return ContentFile(data, name=name)
