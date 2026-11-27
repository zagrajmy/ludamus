from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("db_main", "0204_scrub_email_display_names")]

    operations = [migrations.RemoveField(model_name="party", name="enrolls_together")]
