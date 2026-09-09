from collections import defaultdict

from django.db import migrations, models


def _depth_first(spaces):
    children = defaultdict(list)
    for space in spaces:
        children[space.parent_id].append(space)
    for siblings in children.values():
        siblings.sort(key=lambda space: (space.order, space.name.casefold(), space.pk))

    ordered = []

    def walk(space):
        ordered.append(space)
        for child in children.get(space.pk, []):
            walk(child)

    for root in children.get(None, []):
        walk(root)
    reached = {space.pk for space in ordered}
    ordered.extend(
        sorted(
            (space for space in spaces if space.pk not in reached),
            key=lambda space: (space.order, space.name.casefold(), space.pk),
        )
    )
    return ordered


def backfill_programme_order(apps, schema_editor):
    space_model = apps.get_model("db_main", "Space")
    using = schema_editor.connection.alias
    event_ids = (
        space_model.objects.using(using).values_list("event_id", flat=True).distinct()
    )
    for event_id in event_ids.iterator():
        ordered = _depth_first(
            list(space_model.objects.using(using).filter(event_id=event_id))
        )
        for programme_order, space in enumerate(ordered):
            space.programme_order = programme_order
        space_model.objects.using(using).bulk_update(ordered, ["programme_order"])


class Migration(migrations.Migration):
    dependencies = [("db_main", "0160_eventmappage")]

    operations = [
        migrations.AddField(
            model_name="space",
            name="programme_order",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill_programme_order, migrations.RunPython.noop),
    ]
