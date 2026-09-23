# Replaces stored time slots with per-session availability. The schedule grid
# now derives its days and hours from the event itself, so the only thing worth
# keeping from the old rows is WHEN a facilitator said they could run something,
# in named parts of a day rather than in clock times.

from datetime import datetime, time, timedelta

import django.db.models.deletion
from django.db import migrations, models
from django.utils.timezone import get_current_timezone

# Frozen copies of pacts.availability: a migration must keep behaving the way
# it did the day it was written, whatever the app does later.
_PROGRAMME_DAY_STARTS_AT_HOUR = 6
_PART_HOURS = (
    ("morning", 6, 12),
    ("afternoon", 12, 18),
    ("evening", 18, 24),
    ("night", 24, 30),
)


def _programme_date(moment, tz):
    local = moment.astimezone(tz)
    return (local - timedelta(hours=_PROGRAMME_DAY_STARTS_AT_HOUR)).date()


def _parts_between(start, end, tz):
    """Every (day, part) a window touches.

    Returns:
        A set of (date, part name) pairs.
    """
    touched = set()
    first = _programme_date(start, tz)
    last = _programme_date(end, tz)
    for offset in range((last - first).days + 1):
        day = first + timedelta(days=offset)
        midnight = datetime.combine(day, time(0), tzinfo=tz)
        for name, from_hour, to_hour in _PART_HOURS:
            part_start = midnight + timedelta(hours=from_hour)
            part_end = midnight + timedelta(hours=to_hour)
            if start < part_end and part_start < end:
                touched.add((day, name))
    return touched


def carry_preferences_to_availability(apps, schema_editor):
    """Keep when each session could run; the exact windows are dropped."""
    session_model = apps.get_model("db_main", "Session")
    availability_model = apps.get_model("db_main", "SessionAvailability")
    requirement_model = apps.get_model("db_main", "TimeSlotRequirement")
    category_model = apps.get_model("db_main", "ProposalCategory")
    tz = get_current_timezone()

    rows = []
    for session in session_model.objects.prefetch_related("time_slots"):
        touched = set()
        for slot in session.time_slots.all():
            touched |= _parts_between(slot.start_time, slot.end_time, tz)
        rows.extend(
            availability_model(session_id=session.pk, day=day, part=part)
            for day, part in sorted(touched)
        )
    availability_model.objects.bulk_create(rows, batch_size=500)

    # A category that wired any slot was asking the availability question.
    asked = requirement_model.objects.values_list("category_id", flat=True).distinct()
    category_model.objects.filter(pk__in=list(asked)).update(asks_availability=True)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0165_sphere_subscriptions")]

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
        # Runs while the old tables are still here. Reversing rebuilds empty
        # slot tables: the windows themselves cannot be recovered from parts,
        # so the backwards direction restores the schema, not the data.
        migrations.RunPython(
            carry_preferences_to_availability, migrations.RunPython.noop
        ),
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
