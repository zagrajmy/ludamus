from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING

from django.db import transaction
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


def _save_replacing_files(
    instance: Model, data: Mapping[str, object]
) -> list[tuple[FieldFile, str]]:
    old_names = {
        key: current.name
        for key in data
        if isinstance(current := getattr(instance, key, None), FieldFile)
    }

    written = with_original_names(type(instance), data)
    for key, value in written.items():
        setattr(instance, key, value)
    instance.save(update_fields=list(written))

    return [
        (field_file, old_name)
        for field, old_name in old_names.items()
        if old_name and old_name != (field_file := getattr(instance, field)).name
    ]


def save_replacing_files(instance: Model, data: Mapping[str, object]) -> None:
    for field_file, old_name in _save_replacing_files(instance, data):
        delete_stored_file(field_file, old_name)


def save_replacing_files_on_commit(instance: Model, data: Mapping[str, object]) -> None:
    for field_file, old_name in _save_replacing_files(instance, data):
        transaction.on_commit(partial(delete_stored_file, field_file, old_name))
