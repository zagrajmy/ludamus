import secrets

from django.db import migrations, models


def backfill_invite_tokens(apps, schema_editor):
    Party = apps.get_model("db_main", "Party")
    for party in Party.objects.filter(invite_token=""):
        party.invite_token = secrets.token_urlsafe(32)
        party.save(update_fields=["invite_token"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0126_user_manager")]

    operations = [
        migrations.AlterField(
            model_name="party",
            name="invite_token",
            field=models.CharField(
                db_index=True, default=secrets.token_urlsafe, max_length=64
            ),
        ),
        migrations.RunPython(backfill_invite_tokens, migrations.RunPython.noop),
    ]
