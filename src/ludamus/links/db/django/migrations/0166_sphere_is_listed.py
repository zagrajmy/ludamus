from django.db import migrations, models

KAPIBARRRA_DOMAIN = "kapibarrra.zagrajmy.net"


def unlist_kapibarrra(apps, _schema_editor) -> None:
    sphere = apps.get_model("db_main", "Sphere")
    sphere.objects.filter(site__domain=KAPIBARRRA_DOMAIN).update(is_listed=False)


def relist_kapibarrra(apps, _schema_editor) -> None:
    sphere = apps.get_model("db_main", "Sphere")
    sphere.objects.filter(site__domain=KAPIBARRRA_DOMAIN).update(is_listed=True)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0165_sphere_subscriptions")]

    operations = [
        migrations.AddField(
            model_name="sphere",
            name="is_listed",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(unlist_kapibarrra, relist_kapibarrra),
    ]
