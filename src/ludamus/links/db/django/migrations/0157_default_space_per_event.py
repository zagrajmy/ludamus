from django.db import migrations
from django.utils.text import slugify
from django.utils.translation import gettext

# Inlined rather than imported from models: a historical migration must keep
# doing what it did the day it was written, and a constant in live code can be
# renamed or retranslated under it.
DEFAULT_SPACE_NAME = "Main room"


def add_default_space(apps, schema_editor):
    Event = apps.get_model("db_main", "Event")
    Space = apps.get_model("db_main", "Space")
    name = gettext(DEFAULT_SPACE_NAME)
    spaceless = Event.objects.exclude(
        pk__in=Space.objects.values("event_id")
    ).values_list("pk", flat=True)
    Space.objects.bulk_create(
        Space(event_id=event_pk, parent=None, name=name, slug=slugify(name))
        for event_pk in spaceless
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0156_merge_event_address_and_eventintegration")]

    operations = [migrations.RunPython(add_default_space, migrations.RunPython.noop)]
