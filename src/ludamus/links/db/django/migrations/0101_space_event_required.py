import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0100_backfill_space_event")]

    operations = [
        migrations.AlterField(
            model_name="space",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="spaces",
                to="db_main.event",
            ),
        )
    ]
