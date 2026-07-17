# 0117 only backfilled rows whose status string was "scheduled". Sessions
# placed on the timetable while PENDING / ON_HOLD / REJECTED kept that status,
# violating the "scheduled implies accepted" invariant the panel now enforces.
from django.db import migrations


def backfill_scheduled_sessions_to_accepted(apps, schema_editor):
    Session = apps.get_model("db_main", "Session")
    Session.objects.filter(agenda_item__isnull=False).exclude(status="accepted").update(
        status="accepted"
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0117_backfill_and_remove_session_scheduled_status")]

    operations = [
        migrations.RunPython(
            backfill_scheduled_sessions_to_accepted, migrations.RunPython.noop
        )
    ]
