from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("db_main", "0160_eventmappage")]

    operations = [
        migrations.RenameField(
            model_name="session", old_name="display_name", new_name="facilitator_name"
        )
    ]
