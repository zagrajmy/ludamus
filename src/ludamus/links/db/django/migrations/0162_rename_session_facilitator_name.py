from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("db_main", "0161_space_programme_order")]

    operations = [
        migrations.RenameField(
            model_name="session", old_name="display_name", new_name="facilitator_name"
        )
    ]
