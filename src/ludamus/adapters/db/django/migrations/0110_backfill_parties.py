from django.db import migrations

from ludamus.pacts.party import PartyConsentMode, PartyMembershipStatus


def forwards(apps, schema_editor):
    # One party per manager: the leader plus every connected companion, all
    # ACCEPT_BY_DEFAULT. Runs on historical models — the `User.manager` tree
    # read here is dropped in 0111, so it exists only at this point in the
    # migration graph.
    user_model = apps.get_model("db_main", "User")
    party_model = apps.get_model("db_main", "Party")
    membership_model = apps.get_model("db_main", "PartyMembership")

    manager_ids = (
        user_model.objects.filter(connected__isnull=False)
        .values_list("pk", flat=True)
        .distinct()
    )
    for manager_id in manager_ids:
        party = party_model.objects.create(leader_id=manager_id, name="")
        member_ids = [
            manager_id,
            *user_model.objects.filter(manager_id=manager_id).values_list(
                "pk", flat=True
            ),
        ]
        for member_id in member_ids:
            membership_model.objects.create(
                party=party,
                member_id=member_id,
                consent_mode=PartyConsentMode.ACCEPT_BY_DEFAULT,
                status=PartyMembershipStatus.ACTIVE,
            )


def backwards(apps, schema_editor):
    # Step-1 groundwork is additive and there are no user-created parties yet,
    # so reversing simply clears the backfilled rows. Do NOT reverse after
    # RFC 0001 step 3 ships user-created parties — this wipes them all.
    apps.get_model("db_main", "PartyMembership").objects.all().delete()
    apps.get_model("db_main", "Party").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("db_main", "0109_party_partymembership")]

    operations = [migrations.RunPython(forwards, backwards, elidable=True)]
