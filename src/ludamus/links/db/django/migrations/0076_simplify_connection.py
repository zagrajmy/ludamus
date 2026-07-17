from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("db_main", "0075_connection_last_check_at_and_more")]

    operations = [
        migrations.RemoveField(model_name="connection", name="service"),
        migrations.RemoveField(model_name="connection", name="last_check_status"),
        migrations.RemoveField(model_name="connection", name="last_check_detail"),
        migrations.RemoveField(model_name="connection", name="last_check_at"),
        migrations.RenameField(
            model_name="connection", old_name="credentials", new_name="secret"
        ),
    ]
