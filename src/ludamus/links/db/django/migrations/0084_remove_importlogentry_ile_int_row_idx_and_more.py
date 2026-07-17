from django.db import migrations, models
from django.db.models import Max


def dedupe_log_entries(apps, _schema_editor):
    # Each (integration, row_index) pair is about to become unique. Keep only
    # the most recent row per pair so the constraint can be applied without
    # IntegrityError on existing data.
    entry_model = apps.get_model("db_main", "ImportLogEntry")
    keepers = list(
        entry_model.objects.values("integration_id", "row_index")
        .annotate(max_pk=Max("pk"))
        .values_list("max_pk", flat=True)
    )
    entry_model.objects.exclude(pk__in=keepers).delete()


class Migration(migrations.Migration):

    dependencies = [("db_main", "0083_import_log_entry")]

    operations = [
        migrations.RemoveIndex(model_name="importlogentry", name="ile_int_row_idx"),
        migrations.RunPython(
            dedupe_log_entries, reverse_code=migrations.RunPython.noop
        ),
        migrations.AddConstraint(
            model_name="importlogentry",
            constraint=models.UniqueConstraint(
                fields=("integration", "row_index"), name="ile_unique_integration_row"
            ),
        ),
    ]
