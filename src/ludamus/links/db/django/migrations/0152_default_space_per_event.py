from django.db import migrations
from django.utils.text import slugify

from ludamus.links.db.django.models import DEFAULT_SPACE_NAME


def add_default_space(apps, schema_editor):
    Event = apps.get_model("db_main", "Event")
    Space = apps.get_model("db_main", "Space")
    name = str(DEFAULT_SPACE_NAME)
    spaceless = Event.objects.exclude(
        pk__in=Space.objects.values("event_id")
    ).values_list("pk", flat=True)
    Space.objects.bulk_create(
        Space(event_id=event_pk, parent=None, name=name, slug=slugify(name))
        for event_pk in spaceless
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0151_schedulechangelog_important")]

    operations = [migrations.RunPython(add_default_space, migrations.RunPython.noop)]
