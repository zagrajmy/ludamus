from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("db_main", "0085_announcement"),
        ("db_main", "0088_alter_shadowban_owner_alter_shadowban_target"),
    ]

    operations: list[migrations.operations.base.Operation] = []
