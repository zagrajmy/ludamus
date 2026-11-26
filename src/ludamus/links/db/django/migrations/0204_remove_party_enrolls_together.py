from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("db_main", "0203_listing_party")]

    operations = [migrations.RemoveField(model_name="party", name="enrolls_together")]
