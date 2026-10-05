# NOTE: The address was kept for the lifetime of the RSVP to answer "has this
# IP signed up in the last 60 seconds". The throttle now reserves a cache key
# for the length of that window instead, so the column has no reader left. The
# column is already nullable, so the reverse recreates it as NULL on every row.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("db_main", "0175_merge_schedule_confirmed_notification_kind")]

    operations = [migrations.RemoveField(model_name="encounterrsvp", name="ip_address")]
