from django.db import migrations, models

import ludamus.links.db.django.uploads


class Migration(migrations.Migration):

    dependencies = [("db_main", "0206_merge_20261126_1955")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="uploaded_avatar",
            field=models.ImageField(
                blank=True, upload_to=ludamus.links.db.django.uploads.unique_upload_to
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="uploaded_avatar_original_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
