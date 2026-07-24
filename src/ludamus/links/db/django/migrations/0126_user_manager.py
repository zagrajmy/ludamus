import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_managers(apps, schema_editor):
    user_model = apps.get_model("db_main", "User")
    membership_model = apps.get_model("db_main", "PartyMembership")
    memberships = (
        membership_model.objects.filter(
            member__user_type="connected", status="active", member__manager__isnull=True
        )
        .select_related("party")
        .order_by("member_id", "pk")
    )
    seen = set()
    for membership in memberships:
        if membership.member_id in seen:
            continue
        seen.add(membership.member_id)
        user_model.objects.filter(pk=membership.member_id).update(
            manager_id=membership.party.leader_id
        )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0125_party_invite_token")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="manager",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="connected",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_managers, migrations.RunPython.noop),
    ]
