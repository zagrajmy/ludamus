from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("db_main", "0156_merge_event_address_and_eventintegration")]

    operations = [
        migrations.RenameField(
            model_name="session", old_name="display_name", new_name="facilitator_name"
        )
    ]
