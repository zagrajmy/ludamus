import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0099_event_use_session_cover_placeholders")]

    operations = [
        migrations.AddField(
            model_name="space",
            name="event",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="spaces",
                to="db_main.event",
            ),
        )
    ]
