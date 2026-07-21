from django.db import migrations


def build_tree(apps, schema_editor):
    Venue = apps.get_model("db_main", "Venue")
    Area = apps.get_model("db_main", "Area")
    Space = apps.get_model("db_main", "Space")

    # Idempotency: a linked leaf means the tree is already built.
    if Space.objects.filter(parent__isnull=False).exists():
        return

    venue_to_root = {}
    for venue in Venue.objects.all():
        venue_to_root[venue.pk] = Space.objects.create(
            event_id=venue.event_id,
            parent=None,
            area=None,
            name=venue.name,
            slug=venue.slug,
            description=venue.address,
            order=venue.order,
        )

    area_to_mid = {}
    for area in Area.objects.select_related("venue").all():
        area_to_mid[area.pk] = Space.objects.create(
            event_id=area.venue.event_id,
            parent=venue_to_root[area.venue_id],
            area=None,
            name=area.name,
            slug=area.slug,
            description=area.description,
            order=area.order,
        )

    # Existing leaves keep their pk (AgendaItem FKs untouched); only reparent.
    for space in Space.objects.filter(area__isnull=False, parent__isnull=True):
        space.parent = area_to_mid[space.area_id]
        space.save(update_fields=["parent"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0102_space_tree_fields")]

    operations = [migrations.RunPython(build_tree, migrations.RunPython.noop)]
