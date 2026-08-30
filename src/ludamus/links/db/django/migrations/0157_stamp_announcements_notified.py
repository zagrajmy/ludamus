from django.db import migrations
from django.utils import timezone


def forwards(apps, schema_editor):
    # Stamp pre-existing published announcements as already notified, so the
    # fanout shipping with this release never blasts old news at deploy time.
    apps.get_model("db_main", "Announcement").objects.filter(
        is_published=True, notified_at__isnull=True
    ).update(notified_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ("db_main", "0156_announcement_notified_at_alter_notification_kind_and_more")
    ]

    # The stamp is dropped with the column in 0156's reverse, so nothing to undo.
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
