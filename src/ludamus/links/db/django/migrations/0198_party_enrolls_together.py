from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0197_require_session_space")]

    operations = [
        migrations.AddField(
            model_name="party",
            name="enrolls_together",
            field=models.BooleanField(default=True),
        )
    ]
