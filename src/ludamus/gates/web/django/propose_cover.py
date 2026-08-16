from __future__ import annotations

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

_WIZARD_COVER_KEY = "cover_image_temp"
_WIZARD_COVER_NAME_KEY = "cover_image_temp_name"


def delete_wizard_cover(wizard: dict[str, Any]) -> None:
    if path := wizard.get(_WIZARD_COVER_KEY):
        default_storage.delete(path)
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
    default_storage.delete(path)
    return ContentFile(data, name=name)
