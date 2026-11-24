# 0172 copied AgendaItem.session_confirmed before the dual-writing code
# started. An agenda item confirmed in between has the flag on that column
# only; dropping the column loses it:
# https://github.com/zagrajmy/ludamus/issues/1340
from django.db import migrations


def backfill_schedule_confirmed(apps, _schema_editor):
    session_model = apps.get_model("db_main", "Session")
    session_model.objects.filter(
        agenda_item__session_confirmed=True, schedule_confirmed=False
    ).update(schedule_confirmed=True)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0203_listing_party")]

    operations = [
        migrations.RunPython(backfill_schedule_confirmed, migrations.RunPython.noop)
    ]
