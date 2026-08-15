import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import ludamus.links.db.django.uploads


class Migration(migrations.Migration):

    dependencies = [("db_main", "0141_eventpanelsettings_proposal_columns")]

    operations = [
        migrations.CreateModel(
            name="Guild",
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
                ("name", models.CharField(max_length=255)),
                ("slug", models.SlugField()),
                (
                    "logo",
                    models.FileField(
                        blank=True,
                        upload_to=ludamus.links.db.django.uploads.unique_upload_to,
                    ),
                ),
                ("creation_time", models.DateTimeField(auto_now_add=True)),
                ("modification_time", models.DateTimeField(auto_now=True)),
                (
                    "sphere",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="guilds",
                        to="db_main.sphere",
                    ),
                ),
            ],
            options={"db_table": "guild", "ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="GuildMembership",
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
                ("creation_time", models.DateTimeField(auto_now_add=True)),
                (
                    "guild",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="db_main.guild",
                    ),
                ),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="guild_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "sphere",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="guild_memberships",
                        to="db_main.sphere",
                    ),
                ),
            ],
            options={"db_table": "guild_membership"},
        ),
        migrations.AddField(
            model_name="guild",
            name="members",
            field=models.ManyToManyField(
                related_name="guilds",
                through="db_main.GuildMembership",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="guild",
            constraint=models.UniqueConstraint(
                fields=("sphere", "slug"), name="guild_unique_slug_per_sphere"
            ),
        ),
        migrations.AddConstraint(
            model_name="guildmembership",
            constraint=models.UniqueConstraint(
                fields=("sphere", "member"), name="guild_membership_unique_per_sphere"
            ),
        ),
    ]
