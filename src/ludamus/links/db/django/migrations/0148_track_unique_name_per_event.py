import logging

import django.db.models.functions.text
from django.db import migrations, models
from django.db.models.functions import Lower

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
    # Fold in the database, the same way the constraint about to be added
    # does. Deciding duplication with str.lower() here would let the two
    # disagree on a name and abort AddConstraint mid-deploy.
    existing: dict[int, set[str]] = {}
    folded = track_model.objects.annotate(folded_name=Lower("name"))
    for event_id, folded_name in folded.values_list("event_id", "folded_name"):
        existing.setdefault(event_id, set()).add(folded_name)

    kept: dict[int, set[str]] = {}
    renamed = 0
    tracks = folded.order_by("event_id", "creation_time", "pk")
    for track in tracks.iterator():
        taken = kept.setdefault(track.event_id, set())
        if track.folded_name in taken:
            old_name = track.name
            track.name = _free_name(old_name, taken | existing[track.event_id])
            track.save(update_fields=["name"])
            renamed += 1
            logger.info("0148: track %s name %r -> %r", track.pk, old_name, track.name)
            taken.add(track.name.lower())
        else:
            taken.add(track.folded_name)

    logger.info("0148: %s tracks renamed", renamed)


class Migration(migrations.Migration):

    dependencies = [("db_main", "0147_facilitator_flag_to_soft_delete")]

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
