from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("db_main", "0059_migrate_tags_to_session_fields")]

    operations = [
        migrations.RenameField(
            model_name="eventsettings",
            old_name="filterable_session_fields",
            new_name="displayed_session_fields",
        )
    ]
