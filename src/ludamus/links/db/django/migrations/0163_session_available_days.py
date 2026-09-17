# Replaces stored time slots with per-session available days. The schedule
# grid now derives its days and hours from the event itself, so the only thing
# worth keeping from the old rows is which DAYS a facilitator offered.

import django.db.models.deletion
from django.db import migrations, models
from django.utils.timezone import localtime


def carry_preferences_to_days(apps, schema_editor):
    """Keep each session's offered days; the windows inside them are dropped."""
    session_model = apps.get_model("db_main", "Session")
    day_model = apps.get_model("db_main", "SessionAvailableDay")
    requirement_model = apps.get_model("db_main", "TimeSlotRequirement")
    category_model = apps.get_model("db_main", "ProposalCategory")

    rows = []
    for session in session_model.objects.prefetch_related("time_slots"):
        days = set()
        for slot in session.time_slots.all():
            # A slot running into the small hours offered both dates it
            # touches, so both are kept.
            start = localtime(slot.start_time).date()
            end = localtime(slot.end_time).date()
            days.add(start)
            days.add(end)
        rows.extend(day_model(session_id=session.pk, day=day) for day in sorted(days))
    day_model.objects.bulk_create(rows, batch_size=500)

    # A category that wired any slot was asking the availability question.
    asked = requirement_model.objects.values_list("category_id", flat=True).distinct()
    category_model.objects.filter(pk__in=list(asked)).update(asks_available_days=True)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0162_rename_session_facilitator_name")]

    operations = [
        migrations.CreateModel(
            name="SessionAvailableDay",
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
            ],
            options={"db_table": "session_available_day", "ordering": ["day"]},
        ),
        migrations.AddField(
            model_name="sessionavailableday",
            name="session",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="available_days",
                to="db_main.session",
            ),
        ),
        migrations.AddConstraint(
            model_name="sessionavailableday",
            constraint=models.UniqueConstraint(
                fields=("session", "day"), name="session_has_unique_available_day"
            ),
        ),
        migrations.AddField(
            model_name="proposalcategory",
            name="asks_available_days",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Ask proposers which event days they could run this on."
                    " Off by default: most categories do not need it."
                ),
            ),
        ),
        # Runs while the old tables are still here. Reversing rebuilds empty
        # slot tables: the windows themselves cannot be recovered from days,
        # so the backwards direction restores the schema, not the data.
        migrations.RunPython(carry_preferences_to_days, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="timeslot", name="timeslot_has_unique_times_for_event"
        ),
        migrations.RemoveConstraint(model_name="timeslot", name="timeslot_date_times"),
        migrations.RemoveField(model_name="session", name="time_slots"),
        migrations.RemoveConstraint(
            model_name="timeslotrequirement", name="unique_time_slot_per_category"
        ),
        migrations.RemoveField(model_name="timeslot", name="event"),
        migrations.RemoveField(model_name="timeslotrequirement", name="category"),
        migrations.RemoveField(model_name="timeslotrequirement", name="time_slot"),
        migrations.DeleteModel(name="TimeSlot"),
        migrations.DeleteModel(name="TimeSlotRequirement"),
    ]
