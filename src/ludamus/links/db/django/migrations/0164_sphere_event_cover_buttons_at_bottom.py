from django.db import migrations, models

BACHANALIA_DOMAIN = "bachanalia.zagrajmy.net"


def enable_for_bachanalia(apps, _schema_editor) -> None:
    sphere = apps.get_model("db_main", "Sphere")
    sphere.objects.filter(site__domain=BACHANALIA_DOMAIN).update(
        event_cover_buttons_at_bottom=True
    )


def disable_for_bachanalia(apps, _schema_editor) -> None:
    sphere = apps.get_model("db_main", "Sphere")
    sphere.objects.filter(site__domain=BACHANALIA_DOMAIN).update(
        event_cover_buttons_at_bottom=False
    )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0163_encounters_policy")]

    operations = [
        migrations.AddField(
            model_name="sphere",
            name="event_cover_buttons_at_bottom",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(enable_for_bachanalia, disable_for_bachanalia),
    ]
