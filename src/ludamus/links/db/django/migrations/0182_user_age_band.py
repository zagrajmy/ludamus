from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0181_tags")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="age_band",
            field=models.CharField(
                choices=[
                    ("unknown", "UNKNOWN"),
                    ("13_15", "THIRTEEN_TO_FIFTEEN"),
                    ("16_plus", "SIXTEEN_PLUS"),
                ],
                default="unknown",
                max_length=16,
            ),
        )
    ]
