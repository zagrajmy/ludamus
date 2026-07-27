from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db.models.fields.files import FieldFile

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.db.models import Model

logger = logging.getLogger(__name__)


def delete_stored_file(field_file: object, old_name: str) -> None:
    if (storage := getattr(field_file, "storage", None)) is None:
        return
    try:
        storage.delete(old_name)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Best-effort cleanup of replaced file %r failed", old_name, exc_info=True
        )


def save_replacing_files(instance: Model, data: Mapping[str, object]) -> None:
    # A replaced file field strands its previous blob, because unique_upload_to
    # never reuses a name. Which keys are files is read off the instance rather
    # than listed per repository -- forgetting to list Event.logo is what
    # stranded logos in the first place.
    old_names = {
        key: current.name
        for key in data
        if isinstance(current := getattr(instance, key, None), FieldFile)
    }

    for key, value in data.items():
        setattr(instance, key, value)
    instance.save(update_fields=list(data.keys()))

    for field, old_name in old_names.items():
        field_file = getattr(instance, field)
        if old_name and old_name != field_file.name:
            delete_stored_file(field_file, old_name)
