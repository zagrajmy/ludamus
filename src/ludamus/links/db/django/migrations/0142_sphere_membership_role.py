import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import ludamus.pacts.multiverse


class Migration(migrations.Migration):
    dependencies = [("db_main", "0141_eventpanelsettings_proposal_columns")]

    operations = [
        # `sphere_managers` already exists — Django built it for the plain M2M,
        # with these exact columns and unique index. Adopting it into an
        # explicit through model is a state-only change; the one real schema
        # change is the `role` column added right after.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="SphereMembership",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "sphere",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="db_main.sphere",
                            ),
                        ),
                        (
                            "user",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "sphere_managers",
                        "unique_together": {("sphere", "user")},
                    },
                ),
                migrations.AlterField(
                    model_name="sphere",
                    name="managers",
                    field=models.ManyToManyField(
                        through="db_main.SphereMembership", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ]
        ),
        migrations.AddField(
            model_name="spheremembership",
            name="role",
            field=models.CharField(
                choices=[("manager", "Manager"), ("comms", "Comms")],
                default=ludamus.pacts.multiverse.SphereRole["MANAGER"],
                max_length=20,
            ),
        ),
    ]
