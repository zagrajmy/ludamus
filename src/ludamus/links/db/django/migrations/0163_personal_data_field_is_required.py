"""Personal-data questions apply per event, not per kind.

A field becomes required only when every kind at its event required it; a
missing row counts as optional, and an event with no kinds keeps every field
optional. `order` takes the highest order any kind gave the field.

Reversing gives every kind at the event a row carrying the field's own
`is_required` and `order`. That is the faithful inverse of a transform that
collapsed per-kind rows into one flag, not a restore: which kinds originally
asked for a field is exactly what the forward direction threw away.
"""

from django.db import migrations, models
from django.db.models import Count, Max, Q


def backfill_from_requirements(apps, _schema_editor):
    PersonalDataField = apps.get_model("db_main", "PersonalDataField")
    ProposalCategory = apps.get_model("db_main", "ProposalCategory")
    PersonalDataFieldRequirement = apps.get_model(
        "db_main", "PersonalDataFieldRequirement"
    )

    kinds_per_event = dict(
        ProposalCategory.objects.values_list("event_id")
        .annotate(count=Count("pk"))
        .values_list("event_id", "count")
    )
    usage = {
        row["field_id"]: row
        for row in PersonalDataFieldRequirement.objects.values("field_id").annotate(
            required=Count("pk", filter=Q(is_required=True)), max_order=Max("order")
        )
    }
    for field in PersonalDataField.objects.all():
        row = usage.get(field.pk)
        if row is None:
            continue
        kinds = kinds_per_event.get(field.event_id, 0)
        field.is_required = (
            field.field_type != "checkbox" and kinds > 0 and row["required"] == kinds
        )
        field.order = row["max_order"]
        field.save(update_fields=["is_required", "order"])


def restore_requirements(apps, _schema_editor):
    PersonalDataField = apps.get_model("db_main", "PersonalDataField")
    ProposalCategory = apps.get_model("db_main", "ProposalCategory")
    PersonalDataFieldRequirement = apps.get_model(
        "db_main", "PersonalDataFieldRequirement"
    )

    kinds_per_event = {}
    for event_id, category_id in ProposalCategory.objects.values_list("event_id", "pk"):
        kinds_per_event.setdefault(event_id, []).append(category_id)

    PersonalDataFieldRequirement.objects.bulk_create(
        PersonalDataFieldRequirement(
            field_id=field.pk,
            category_id=category_id,
            is_required=field.is_required,
            order=field.order,
        )
        for field in PersonalDataField.objects.all()
        for category_id in kinds_per_event.get(field.event_id, ())
    )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0162_rename_session_facilitator_name")]

    operations = [
        migrations.AddField(
            model_name="personaldatafield",
            name="is_required",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(backfill_from_requirements, restore_requirements),
        migrations.AddConstraint(
            model_name="personaldatafield",
            constraint=models.CheckConstraint(
                condition=~Q(field_type="checkbox", is_required=True),
                name="personal_data_field_checkbox_not_required",
            ),
        ),
        migrations.DeleteModel(name="PersonalDataFieldRequirement"),
    ]
