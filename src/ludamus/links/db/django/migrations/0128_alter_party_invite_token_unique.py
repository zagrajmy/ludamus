import secrets

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("db_main", "0127_alter_party_invite_token")]

    operations = [
        migrations.AlterField(
            model_name="party",
            name="invite_token",
            field=models.CharField(
                db_index=True, default=secrets.token_urlsafe, max_length=64, unique=True
            ),
        )
    ]
