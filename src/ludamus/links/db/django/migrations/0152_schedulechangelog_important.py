from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0151_track_unique_name_per_event")]

    operations = [
        migrations.AddField(
            model_name="schedulechangelog",
            name="important",
            field=models.BooleanField(default=False),
        )
    ]
