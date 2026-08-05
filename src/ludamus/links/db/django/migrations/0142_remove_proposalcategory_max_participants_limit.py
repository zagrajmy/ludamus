from django.db import migrations


class Migration(migrations.Migration):
    # Reversible: RemoveField re-adds the column at its default (0 = no
    # ceiling). The per-category values themselves don't survive a rollback,
    # and nothing read them except the submission wizard's input bound.

    dependencies = [("db_main", "0141_eventpanelsettings_proposal_columns")]

    operations = [
        migrations.RemoveField(
            model_name="proposalcategory", name="max_participants_limit"
        )
    ]
