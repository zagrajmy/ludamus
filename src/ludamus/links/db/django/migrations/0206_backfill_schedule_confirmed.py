# NOTE: AgendaItem.session_confirmed is the source of truth until its column is
# dropped: https://github.com/zagrajmy/ludamus/issues/1340
from django.db import migrations


def backfill_schedule_confirmed(apps, _schema_editor):
    session_model = apps.get_model("db_main", "Session")
    confirmed = session_model.objects.filter(agenda_item__session_confirmed=True)
    session_model.objects.filter(pk__in=confirmed.values("pk")).update(
        schedule_confirmed=True
    )
    session_model.objects.exclude(pk__in=confirmed.values("pk")).update(
        schedule_confirmed=False
    )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0205_remove_party_enrolls_together")]

    operations = [
        migrations.RunPython(backfill_schedule_confirmed, migrations.RunPython.noop)
    ]
