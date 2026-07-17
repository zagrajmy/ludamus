from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("db_main", "0027_add_field_type_and_options")]

    operations = [
        migrations.AddField(
            model_name="proposalcategory",
            name="durations",
            field=models.JSONField(default=list),
        )
    ]
