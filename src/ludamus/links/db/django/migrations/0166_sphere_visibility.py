from django.db import migrations, models

KAPIBARRRA_DOMAIN = "kapibarrra.zagrajmy.net"


def make_kapibarrra_private(apps, _schema_editor) -> None:
    sphere = apps.get_model("db_main", "Sphere")
    sphere.objects.filter(site__domain=KAPIBARRRA_DOMAIN).update(visibility="private")


def make_kapibarrra_public(apps, _schema_editor) -> None:
    sphere = apps.get_model("db_main", "Sphere")
    sphere.objects.filter(site__domain=KAPIBARRRA_DOMAIN).update(visibility="public")


class Migration(migrations.Migration):
    dependencies = [("db_main", "0165_sphere_subscriptions")]

    operations = [
        migrations.AddField(
            model_name="sphere",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("unlisted", "Unlisted"),
                    ("private", "Private"),
                ],
                default="public",
                max_length=20,
            ),
        ),
        migrations.RunPython(make_kapibarrra_private, make_kapibarrra_public),
    ]
