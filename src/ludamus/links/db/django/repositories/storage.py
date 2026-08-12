from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db.models.fields.files import FieldFile

from ludamus.pacts.images import original_filename

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.db.models import Model

logger = logging.getLogger(__name__)


def with_original_names[T: Model, V](
    model: type[T], data: Mapping[str, V]
) -> dict[str, V | str]:
    written: dict[str, V | str] = dict(data)
    for field, value in data.items():
        companion = f"{field}_original_name"
        if not hasattr(model, companion):
            continue
        name = getattr(value, "name", "") if value else ""
        written[companion] = original_filename(name) if name else ""
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

    written = with_original_names(type(instance), data)
    for key, value in written.items():
        setattr(instance, key, value)
    instance.save(update_fields=list(written))

    for field, old_name in old_names.items():
        field_file = getattr(instance, field)
        if old_name and old_name != field_file.name:
            delete_stored_file(field_file, old_name)
