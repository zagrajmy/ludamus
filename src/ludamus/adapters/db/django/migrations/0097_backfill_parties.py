from django.db import migrations

from ludamus.links.db.django.party_backfill import backfill_parties


def forwards(apps, schema_editor):
    backfill_parties(
        user_model=apps.get_model("db_main", "User"),
        party_model=apps.get_model("db_main", "Party"),
        membership_model=apps.get_model("db_main", "PartyMembership"),
    )


def backwards(apps, schema_editor):
    # Step-1 groundwork is additive and there are no user-created parties yet,
    # so reversing simply clears the backfilled rows.
    apps.get_model("db_main", "PartyMembership").objects.all().delete()
    apps.get_model("db_main", "Party").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("db_main", "0096_party_partymembership")]

    operations = [migrations.RunPython(forwards, backwards)]
