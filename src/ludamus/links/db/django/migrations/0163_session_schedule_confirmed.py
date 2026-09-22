from django.db import migrations, models


def backfill_schedule_confirmed(apps, _schema_editor):
    session_model = apps.get_model("db_main", "Session")
    session_model.objects.filter(agenda_item__session_confirmed=True).update(
        schedule_confirmed=True
    )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0165_sphere_subscriptions")]

    operations = [
        migrations.AddField(
            model_name="session",
            name="schedule_confirmed",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_schedule_confirmed, migrations.RunPython.noop),
    ]
