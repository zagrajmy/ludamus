from __future__ import annotations

from typing import TYPE_CHECKING

import django.db.models.deletion
from django.db import migrations, models

import ludamus.links.db.django.models

if TYPE_CHECKING:
    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def _image_to_page(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    event_map = apps.get_model("db_main", "EventMap")
    page = apps.get_model("db_main", "EventMapPage")
    page.objects.bulk_create(
        page(
            event_map_id=row.pk,
            image=row.image,
            image_original_name=row.image_original_name,
            order=0,
        )
        for row in event_map.objects.using(schema_editor.connection.alias).all()
    )


def _page_to_image(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    page = apps.get_model("db_main", "EventMapPage")
    event_map = apps.get_model("db_main", "EventMap")
    using = schema_editor.connection.alias
    for row in page.objects.using(using).filter(order=0):
        event_map.objects.using(using).filter(pk=row.event_map_id).update(
            image=row.image, image_original_name=row.image_original_name
        )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0159_default_space_per_event")]

    operations = [
        migrations.CreateModel(
            name="EventMapPage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        upload_to=ludamus.links.db.django.models.unique_upload_to
                    ),
                ),
                (
                    "image_original_name",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("order", models.PositiveIntegerField(default=0)),
                (
                    "event_map",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pages",
                        to="db_main.eventmap",
                    ),
                ),
            ],
            options={"db_table": "event_map_page", "ordering": ["order", "pk"]},
        ),
        migrations.RunPython(_image_to_page, _page_to_image),
        migrations.RemoveField(model_name="eventmap", name="image"),
        migrations.RemoveField(model_name="eventmap", name="image_original_name"),
    ]
