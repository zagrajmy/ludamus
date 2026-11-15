# Narrows time slots to one job, availability. The schedule grid now derives its
# days and hours from the event itself, and a category no longer wires slots:
# it asks whether a facilitator could run its sessions, answered in the event's
# time slots where it lists any and in named parts of a day where it does not.
# The slots and every session's chosen slots stay as they are.

import django.db.models.deletion
from django.db import migrations, models


def ask_where_slots_were_wired(apps, schema_editor):
    """Ask when proposers could host in every category that wired a slot."""
    requirement_model = apps.get_model("db_main", "TimeSlotRequirement")
    category_model = apps.get_model("db_main", "ProposalCategory")
    asked = requirement_model.objects.values_list("category_id", flat=True).distinct()
    category_model.objects.filter(pk__in=list(asked)).update(asks_availability=True)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0197_require_session_space")]

    operations = [
        migrations.CreateModel(
            name="SessionAvailability",
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
                ("day", models.DateField()),
                (
                    "part",
                    models.CharField(
                        choices=[
                            ("morning", "MORNING"),
                            ("afternoon", "AFTERNOON"),
                            ("evening", "EVENING"),
                            ("night", "NIGHT"),
                        ],
                        max_length=9,
                    ),
                ),
            ],
            options={"db_table": "session_availability", "ordering": ["day", "part"]},
        ),
        migrations.AddField(
            model_name="sessionavailability",
            name="session",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="availability",
                to="db_main.session",
            ),
        ),
        migrations.AddConstraint(
            model_name="sessionavailability",
            constraint=models.UniqueConstraint(
                fields=("session", "day", "part"),
                name="session_has_unique_availability",
            ),
        ),
        migrations.AddField(
            model_name="proposalcategory",
            name="asks_availability",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Ask proposers when they could run this. Off by default:"
                    " most categories do not need it."
                ),
            ),
        ),
        # Runs while the requirements are still here. Reversing rebuilds an
        # empty requirement table: which category wired which slot is not
        # recoverable from the flag, so the backwards direction restores the
        # schema, not the data.
        migrations.RunPython(ask_where_slots_were_wired, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="timeslotrequirement", name="unique_time_slot_per_category"
        ),
        migrations.RemoveField(model_name="timeslotrequirement", name="category"),
        migrations.RemoveField(model_name="timeslotrequirement", name="time_slot"),
        migrations.DeleteModel(name="TimeSlotRequirement"),
    ]
