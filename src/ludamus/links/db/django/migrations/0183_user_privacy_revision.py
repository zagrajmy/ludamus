import uuid
from itertools import batched

from django.db import migrations, models


def assign_privacy_revisions(apps, schema_editor):
    users = apps.get_model("db_main", "User").objects.using(
        schema_editor.connection.alias
    )
    for batch in batched(users.only("pk").iterator(chunk_size=500), 500, strict=False):
        for user in batch:
            user.privacy_revision = uuid.uuid4()
        users.bulk_update(batch, ["privacy_revision"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0182_user_age_band")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="privacy_revision",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(assign_privacy_revisions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="privacy_revision",
            field=models.UUIDField(default=uuid.uuid4, editable=False),
        ),
    ]
