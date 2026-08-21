# A move used to be readable only as "an unassign and an assign a blink
# apart", which a slow transaction breaks. It is recorded at write time now;
# rows written before this migration get the link from that old rule, applied
# once, here.
from datetime import timedelta

import django.db.models.deletion
from django.db import migrations, models

_MOVE_WINDOW = timedelta(seconds=5)


def link_existing_moves(apps, schema_editor):
    ScheduleChangeLog = apps.get_model("db_main", "ScheduleChangeLog")
    logs = ScheduleChangeLog.objects.order_by("session_id", "creation_time", "pk")
    previous = None
    linked = []
    for log in logs:
        if (
            previous is not None
            and previous.session_id == log.session_id
            and previous.action == "unassign"
            and log.action == "assign"
            and log.creation_time - previous.creation_time <= _MOVE_WINDOW
        ):
            log.moved_from_id = previous.pk
            linked.append(log)
            previous = None
            continue
        previous = log
    ScheduleChangeLog.objects.bulk_update(linked, ["moved_from"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [("db_main", "0148_schedule_change_log_acknowledgement")]

    operations = [
        migrations.AddField(
            model_name="schedulechangelog",
            name="moved_from",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="moved_to",
                to="db_main.schedulechangelog",
            ),
        ),
        migrations.RunPython(link_existing_moves, migrations.RunPython.noop),
    ]
