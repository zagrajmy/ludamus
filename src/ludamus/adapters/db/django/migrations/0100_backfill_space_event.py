from django.db import migrations


def backfill_event(apps, schema_editor):
    Space = apps.get_model("db_main", "Space")
    # Every space is a leaf today; its event is its area's venue's event.
    for space in Space.objects.filter(event__isnull=True).select_related("area__venue"):
        space.event_id = space.area.venue.event_id
        space.save(update_fields=["event"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0099_space_event")]

    operations = [migrations.RunPython(backfill_event, migrations.RunPython.noop)]
