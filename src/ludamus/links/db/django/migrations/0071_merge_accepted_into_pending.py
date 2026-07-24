from django.db import migrations, models


def merge_accepted_into_pending(apps, schema_editor):
    Session = apps.get_model("db_main", "Session")
    Session.objects.filter(status="accepted").update(status="pending")


class Migration(migrations.Migration):

    dependencies = [("db_main", "0070_agendaitem_agenda_item_space_time_idx")]

    operations = [
        migrations.RunPython(merge_accepted_into_pending, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="session",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "PENDING"),
                    ("rejected", "REJECTED"),
                    ("scheduled", "SCHEDULED"),
                ],
                default="pending",
                max_length=15,
            ),
        ),
    ]
