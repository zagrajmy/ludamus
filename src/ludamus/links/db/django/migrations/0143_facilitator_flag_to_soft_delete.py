from django.db import migrations
from django.utils import timezone


def flag_to_deleted_at(apps, schema_editor):
    # The flag was a triage marker, not a deletion: flagged facilitators stayed
    # live, on their sessions and in every picker. Carrying one over to
    # `deleted_at` therefore takes a name out of the program, so only the
    # flagged rows running no session convert — exactly the ones an organizer
    # can delete by hand now. A flagged facilitator still on a session keeps
    # its byline and only loses the marker, which nothing else read.
    # Reversible: a dead row flags again.
    facilitator = apps.get_model("db_main", "Facilitator")
    # Any session at all holds the conversion up, deleted ones included —
    # matching `FacilitatorRepository.has_sessions`. A deleted session is
    # restorable, so converting its facilitator here would hand the restore a
    # session with a missing byline.
    running_a_session = facilitator.objects.filter(sessions__isnull=False).values("pk")
    facilitator.objects.filter(
        flagged_for_deletion=True, deleted_at__isnull=True
    ).exclude(pk__in=running_a_session).update(deleted_at=timezone.now())


def deleted_at_to_flag(apps, schema_editor):
    facilitator = apps.get_model("db_main", "Facilitator")
    facilitator.objects.filter(deleted_at__isnull=False).update(
        flagged_for_deletion=True
    )


class Migration(migrations.Migration):

    dependencies = [("db_main", "0142_facilitator_deleted_at")]

    operations = [
        migrations.RunPython(flag_to_deleted_at, deleted_at_to_flag),
        migrations.RemoveField(model_name="facilitator", name="flagged_for_deletion"),
    ]
