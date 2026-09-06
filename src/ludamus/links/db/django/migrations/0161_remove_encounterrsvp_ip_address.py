# NOTE: The address was kept for the lifetime of the RSVP to answer "has this
# IP signed up in the last 60 seconds". The throttle now reserves a cache key
# for the length of that window instead, so the column has no reader left.
#
# The field is made nullable before it is dropped: a bare RemoveField reverses
# into a NOT NULL column with no default, which fails on a populated table.
#
# SAFETY: reversing on a populated table still isn't enough on its own —
# RemoveField's reverse recreates the column with every row NULL (the real
# addresses are gone), and the AlterField reverse right after tries to make
# that NULL-filled column NOT NULL again, which fails the same way. The
# backfill below (a no-op going forward) runs between the two on reverse and
# fills the gap with a sentinel so the NOT NULL restore has something to bite.

from django.db import migrations, models


def _noop(apps, schema_editor):
    del apps, schema_editor


def _backfill_null_ip_address(apps, schema_editor):
    del schema_editor
    apps.get_model("db_main", "EncounterRSVP").objects.filter(
        ip_address__isnull=True
    ).update(ip_address="unknown")


class Migration(migrations.Migration):

    dependencies = [("db_main", "0160_eventmappage")]

    operations = [
        migrations.AlterField(
            model_name="encounterrsvp",
            name="ip_address",
            field=models.GenericIPAddressField(null=True),
        ),
        migrations.RunPython(_noop, _backfill_null_ip_address),
        migrations.RemoveField(model_name="encounterrsvp", name="ip_address"),
    ]
