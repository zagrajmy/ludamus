# NOTE: The address was kept for the lifetime of the RSVP to answer "has this
# IP signed up in the last 60 seconds". The throttle now reserves a cache key
# for the length of that window instead, so the column has no reader left.
#
# The field is made nullable before it is dropped: a bare RemoveField reverses
# into a NOT NULL column with no default, which fails on a populated table.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0160_eventmappage")]

    operations = [
        migrations.AlterField(
            model_name="encounterrsvp",
            name="ip_address",
            field=models.GenericIPAddressField(null=True),
        ),
        migrations.RemoveField(model_name="encounterrsvp", name="ip_address"),
    ]
