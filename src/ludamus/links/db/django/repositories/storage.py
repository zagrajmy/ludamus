from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.files.base import File
from django.db.models.fields.files import FieldFile

from ludamus.links.db.django.previews import image_preview
from ludamus.pacts.images import original_filename

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.db.models import Model

logger = logging.getLogger(__name__)


def _original_name(value: object) -> str:
    name = getattr(value, "name", "") if value else ""
    return original_filename(name) if name else ""


def _preview(value: object) -> str:
    # A cleared field arrives as "" and a rename as a plain string; only a file
    # has bytes to read, and only bytes make a preview.
    return image_preview(value) if isinstance(value, File) else ""


# A field can carry companions the writer never names: what the file was called
# before storage renamed it, and its inline preview. Both are derived here off
# the model, so no repository keeps its own list of which fields have which.
_COMPANIONS = {"_original_name": _original_name, "_preview": _preview}


def with_file_companions[T: Model, V](
    model: type[T], data: Mapping[str, V]
) -> dict[str, V | str]:
    """Add each written file field's derived companion fields.

    Returns:
        The data, plus a value for every companion field the model declares.
    """
    written: dict[str, V | str] = dict(data)
    for field, value in data.items():
        for suffix, derive in _COMPANIONS.items():
            if hasattr(model, companion := f"{field}{suffix}"):
                written[companion] = derive(value)
    return written


def delete_stored_file(field_file: FieldFile, old_name: str) -> None:
    try:
        field_file.storage.delete(old_name)
    except Exception:
        logger.warning(
            "Best-effort cleanup of replaced file %r failed", old_name, exc_info=True
        )


def save_replacing_files(instance: Model, data: Mapping[str, object]) -> None:
    # A replaced file field strands its previous blob, because unique_upload_to
    # never reuses a name. Which keys are files is read off the instance, so no
    # repository has to maintain its own list.
    old_names = {
        key: current.name
        for key in data
        if isinstance(current := getattr(instance, key, None), FieldFile)
    }

    written = with_file_companions(type(instance), data)
    for key, value in written.items():
        setattr(instance, key, value)
    instance.save(update_fields=list(written))

    for field, old_name in old_names.items():
        field_file = getattr(instance, field)
        if old_name and old_name != field_file.name:
            delete_stored_file(field_file, old_name)
