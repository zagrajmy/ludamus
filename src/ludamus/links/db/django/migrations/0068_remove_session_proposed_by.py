from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("db_main", "0067_populate_facilitators_from_proposed_by")]

    operations = [migrations.RemoveField(model_name="session", name="proposed_by")]
