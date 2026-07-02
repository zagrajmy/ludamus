from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("db_main", "0105_space_space_root_has_unique_slug_per_event")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="claim_token",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=64
            ),
        )
    ]
