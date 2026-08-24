"""Fill in inline previews for covers uploaded before the column existed."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import migrations

from ludamus.links.db.django.previews import image_preview

if TYPE_CHECKING:
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.state import StateApps

logger = logging.getLogger(__name__)


def fill_previews(apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    event_model = apps.get_model("db_main", "Event")
    for event in event_model.objects.exclude(cover_image="").iterator():
        # Reads every cover out of storage, so it is slow in proportion to how
        # many events a sphere has ever run — tens, not millions. A cover that
        # cannot be read leaves the column empty, which is the same state every
        # event was in a moment ago.
        try:
            with event.cover_image.open("rb"):
                event.cover_image_preview = image_preview(event.cover_image)
        except Exception:
            logger.warning(
                "Skipping cover preview for event %s", event.pk, exc_info=True
            )
            continue
        event.save(update_fields=["cover_image_preview"])


def clear_previews(apps: StateApps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    apps.get_model("db_main", "Event").objects.update(cover_image_preview="")


class Migration(migrations.Migration):

    dependencies = [("db_main", "0152_event_cover_image_preview")]

    operations = [migrations.RunPython(fill_previews, clear_previews)]
