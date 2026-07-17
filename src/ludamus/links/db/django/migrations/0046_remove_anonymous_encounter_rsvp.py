"""Remove anonymous encounter RSVPs and make user mandatory."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_anonymous_rsvps(apps, _schema_editor):
    EncounterRSVP = apps.get_model("db_main", "EncounterRSVP")
    EncounterRSVP.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("db_main", "0045_sphere_default_page_sphere_enabled_pages_encounter_and_more")
    ]

    operations = [
        # 1. Delete anonymous RSVPs before schema change
        migrations.RunPython(delete_anonymous_rsvps, migrations.RunPython.noop),
        # 2. Remove old constraints
        migrations.RemoveConstraint(
            model_name="encounterrsvp", name="encounter_rsvp_user_or_name"
        ),
        migrations.RemoveConstraint(
            model_name="encounterrsvp", name="encounter_rsvp_unique_user"
        ),
        # 3. Make user non-nullable
        migrations.AlterField(
            model_name="encounterrsvp",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="encounter_rsvps",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 4. Add unconditional unique constraint
        migrations.AddConstraint(
            model_name="encounterrsvp",
            constraint=models.UniqueConstraint(
                fields=("encounter", "user"), name="encounter_rsvp_unique_user"
            ),
        ),
        # 5. Remove name field
        migrations.RemoveField(model_name="encounterrsvp", name="name"),
    ]
