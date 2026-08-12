from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from django.db.models import Model
from django.db.models.fields.files import FieldFile

from ludamus.pacts.images import ORIGINAL_FILENAME_MAX_LENGTH

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)


def original_filename(name: str) -> str:
    return Path(name.replace("\\", "/")).name[:ORIGINAL_FILENAME_MAX_LENGTH]


def bind_original_names(instance: Model, field_names: Iterable[str]) -> list[str]:
    original_keys = []
    for field in field_names:
        current = getattr(instance, field, None)
        if not isinstance(current, FieldFile):
            continue
        original_key = f"{field}_original_name"
        setattr(
            instance,
            original_key,
            original_filename(current.name or "") if current else "",
        )
        original_keys.append(original_key)
    return original_keys


def persist[T: Model, V](model: type[T], data: Mapping[str, V]) -> T:
    instance = model(**data)
    bind_original_names(instance, data)
    instance.save()
    return instance


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

    for key, value in data.items():
        setattr(instance, key, value)
    original_keys = bind_original_names(instance, data)
    instance.save(update_fields=[*data.keys(), *original_keys])

    for field, old_name in old_names.items():
        field_file = getattr(instance, field)
        if old_name and old_name != field_file.name:
            delete_stored_file(field_file, old_name)
