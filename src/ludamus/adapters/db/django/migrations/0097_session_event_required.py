import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0096_backfill_session_event")]

    operations = [
        migrations.AlterField(
            model_name="session",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="event_sessions",
                to="db_main.event",
            ),
        )
    ]
