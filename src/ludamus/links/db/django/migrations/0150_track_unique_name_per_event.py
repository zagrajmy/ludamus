import logging

import django.db.models.functions.text
from django.db import migrations, models
from django.db.models import Value
from django.db.models.functions import Lower

logger = logging.getLogger(__name__)

NAME_MAX_LENGTH = 255


def _folded(track_model, event_id, name):
    # One folding authority: the database, exactly as the constraint folds.
    # Deciding any of this with str.lower() lets Python and the database
    # disagree on a name and abort AddConstraint mid-deploy.
    return (
        track_model.objects.filter(event_id=event_id)
        .annotate(folded_name=Lower("name"))
        .filter(folded_name=Lower(Value(name)))
    )


def _free_name(track_model, event_id, base):
    # Every track of this event is already stored, renames included, so asking
    # the database covers both the names kept so far and the ones still ahead.
    counter = 2
    while True:
        suffix = f" ({counter})"
        candidate = base[: NAME_MAX_LENGTH - len(suffix)] + suffix
        if not _folded(track_model, event_id, candidate).exists():
            return candidate
        counter += 1


def rename_duplicate_track_names(apps, schema_editor):
    del schema_editor
    track_model = apps.get_model("db_main", "Track")
    kept: dict[int, set[str]] = {}
    renamed = 0
    folded = track_model.objects.annotate(folded_name=Lower("name"))
    tracks = folded.order_by("event_id", "creation_time", "pk")
    for track in tracks.iterator():
        # The oldest row of each name keeps it; every later one counts up.
        taken = kept.setdefault(track.event_id, set())
        if track.folded_name in taken:
            old_name = track.name
            track.name = _free_name(track_model, track.event_id, old_name)
            track.save(update_fields=["name"])
            renamed += 1
            logger.info("0150: track %s name %r -> %r", track.pk, old_name, track.name)
            taken.add(
                folded.filter(pk=track.pk).values_list("folded_name", flat=True).first()
            )
        else:
            taken.add(track.folded_name)

    logger.info("0150: %s tracks renamed", renamed)


class Migration(migrations.Migration):

    dependencies = [("db_main", "0149_schedulechangelog_moved_from")]

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
