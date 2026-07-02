from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("db_main", "0107_sessionbookmark")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="claim_token",
            field=models.CharField(
                blank=True, db_index=True, default="", max_length=64
            ),
        )
    ]
