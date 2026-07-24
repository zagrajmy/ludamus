from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0080_eventintegration_settings_json")]

    operations = [
        migrations.AddField(
            model_name="eventintegration",
            name="questions_snapshot_json",
            field=models.TextField(default="[]"),
        )
    ]
