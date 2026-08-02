from django.db import migrations
from django.utils import timezone


def flag_to_deleted_at(apps, schema_editor):
    # The deletion flag always meant "gone as far as the program is concerned",
    # so flagged rows become deleted ones. Reversible: a dead row flags again.
    facilitator = apps.get_model("db_main", "Facilitator")
    facilitator.objects.filter(
        flagged_for_deletion=True, deleted_at__isnull=True
    ).update(deleted_at=timezone.now())


def deleted_at_to_flag(apps, schema_editor):
    facilitator = apps.get_model("db_main", "Facilitator")
    facilitator.objects.filter(deleted_at__isnull=False).update(
        flagged_for_deletion=True
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0140_facilitator_deleted_at")]

    operations = [
        migrations.RunPython(flag_to_deleted_at, deleted_at_to_flag),
        migrations.RemoveField(model_name="facilitator", name="flagged_for_deletion"),
    ]
