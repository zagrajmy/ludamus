from django.db import migrations, models

import ludamus.links.db.django.uploads


def copy_gravatar_flag_to_source(apps, _schema_editor):
    user_model = apps.get_model("db_main", "User")
    user_model.objects.filter(use_gravatar=True).update(avatar_source="gravatar")


def copy_source_to_gravatar_flag(apps, _schema_editor):
    user_model = apps.get_model("db_main", "User")
    user_model.objects.filter(avatar_source="gravatar").update(use_gravatar=True)


class Migration(migrations.Migration):

    dependencies = [("db_main", "0206_merge_20261126_1955")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar_source",
            field=models.CharField(
                choices=[
                    ("uploaded", "UPLOADED"),
                    ("provider", "PROVIDER"),
                    ("gravatar", "GRAVATAR"),
                ],
                default="provider",
                help_text="Which picture the member picked as their avatar",
                max_length=16,
                verbose_name="Avatar source",
            ),
        ),
        migrations.RunPython(
            copy_gravatar_flag_to_source, copy_source_to_gravatar_flag
        ),
        migrations.RemoveField(model_name="user", name="use_gravatar"),
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
