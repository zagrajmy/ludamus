from django.db import migrations
from django.utils import timezone

# Frozen copies — never import live enums into a migration.
OCCUPYING_STATUSES = ("confirmed", "offered")
SOURCE_BACKFILL = "backfill"


def forwards(apps, schema_editor):
    participation_model = apps.get_model("db_main", "SessionParticipation")
    subscription_model = apps.get_model("db_main", "NotificationSubscription")
    announcement_model = apps.get_model("db_main", "Announcement")

    now = timezone.now()
    pairs = (
        participation_model.objects.filter(
            status__in=OCCUPYING_STATUSES, session__event__end_time__gte=now
        )
        .values_list("user_id", "session__event_id")
        .distinct()
    )
    subscription_model.objects.bulk_create(
        [
            subscription_model(
                user_id=user_id, event_id=event_id, source=SOURCE_BACKFILL
            )
            for user_id, event_id in pairs
        ],
        ignore_conflicts=True,
    )

    # Stamp pre-existing published announcements as already notified, so the
    # fanout shipping with this release never blasts old news at deploy time.
    announcement_model.objects.filter(
        is_published=True, notified_at__isnull=True
    ).update(notified_at=now)


def backwards(apps, schema_editor):
    # Backfilled rows are tagged by source; the notified_at stamp is dropped
    # with the column in 0155's reverse, so nothing to undo here beyond ours.
    apps.get_model("db_main", "NotificationSubscription").objects.filter(
        source=SOURCE_BACKFILL
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("db_main", "0155_announcement_notified_at_alter_notification_kind_and_more")
    ]

    operations = [migrations.RunPython(forwards, backwards, elidable=True)]
