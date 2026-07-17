from django.db import migrations, models

# The columns every list showed before they became configurable, in the order
# the template hardcoded them. Personal-data columns were appended after these.
_BUILTIN_COLUMNS = ["name", "linked", "sessions", "accreditation"]


def populate_columns(apps, schema_editor):
    settings_model = apps.get_model("db_main", "EventPanelSettings")
    for settings in settings_model.objects.prefetch_related(
        "displayed_facilitator_fields"
    ):
        fields = sorted(
            settings.displayed_facilitator_fields.all(),
            key=lambda field: (field.order, field.name),
        )
        # No chosen fields renders identically to the default set, so those
        # rows stay empty rather than freezing today's defaults into data.
        if not fields:
            continue
        settings.facilitator_columns = [
            *_BUILTIN_COLUMNS,
            *(f"field_{field.pk}" for field in fields),
        ]
        settings.save(update_fields=["facilitator_columns"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0130_merge_20260715_1230")]

    operations = [
        migrations.AddField(
            model_name="eventpanelsettings",
            name="facilitator_columns",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(populate_columns, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="eventpanelsettings", name="displayed_facilitator_fields"
        ),
    ]
