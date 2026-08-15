import logging

import django.db.models.functions.text
from django.db import migrations, models

logger = logging.getLogger(__name__)

NAME_MAX_LENGTH = 255


def _free_name(base, taken):
    counter = 2
    while True:
        suffix = f" ({counter})"
        candidate = base[: NAME_MAX_LENGTH - len(suffix)] + suffix
        if candidate.lower() not in taken:
            return candidate
        counter += 1


def rename_duplicate_track_names(apps, schema_editor):
    del schema_editor
    track_model = apps.get_model("db_main", "Track")
    # Every name the event already carries, so a counter suffix never lands on
    # a distinct track further down the ordering.
    existing: dict[int, set[str]] = {}
    for event_id, name in track_model.objects.values_list("event_id", "name"):
        existing.setdefault(event_id, set()).add(name.lower())

    kept: dict[int, set[str]] = {}
    renamed = 0
    tracks = track_model.objects.order_by("event_id", "creation_time", "pk")
    for track in tracks.iterator():
        taken = kept.setdefault(track.event_id, set())
        if track.name.lower() in taken:
            old_name = track.name
            track.name = _free_name(old_name, taken | existing[track.event_id])
            track.save(update_fields=["name"])
            renamed += 1
            logger.info("0147: track %s name %r -> %r", track.pk, old_name, track.name)
        taken.add(track.name.lower())

    logger.info("0147: %s tracks renamed", renamed)


class Migration(migrations.Migration):

    dependencies = [("db_main", "0146_facilitator_is_collective")]

    operations = [
        migrations.RunPython(rename_duplicate_track_names, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="track",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                models.F("event"),
                name="track_unique_name_per_event",
            ),
        ),
    ]
