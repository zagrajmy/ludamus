from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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


def save_replacing_files(
    instance: Model, data: Mapping[str, object], *file_fields: str
) -> None:
    # A replaced file field strands its previous blob, because unique_upload_to
    # never reuses a name. Naming the file fields here keeps the cleanup from
    # being something each repository has to remember on its own.
    old_names = {
        field: getattr(instance, field).name for field in file_fields if field in data
    }

    for key, value in data.items():
        setattr(instance, key, value)
    instance.save(update_fields=list(data.keys()))

    for field, old_name in old_names.items():
        field_file = getattr(instance, field)
        if old_name and old_name != field_file.name:
            delete_stored_file(field_file, old_name)
