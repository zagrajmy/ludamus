from django.db import migrations


def _is_blank(value):
    # `value` is a JSONField: importers wrote "" for unanswered questions and
    # the panel form writes [] for an unselected multi-select. Both mean
    # "absent". False / 0 are real answers and stay.
    if isinstance(value, str):
        return not value.strip()
    return value == []


def _purge(model):
    blank_pks = [
        pk for pk, value in model.objects.values_list("pk", "value") if _is_blank(value)
    ]
    model.objects.filter(pk__in=blank_pks).delete()


def purge_blank_field_values(apps, schema_editor):
    _purge(apps.get_model("db_main", "SessionFieldValue"))
    _purge(apps.get_model("db_main", "PersonalDataFieldValue"))


class Migration(migrations.Migration):

    dependencies = [
        (
            "db_main",
            "0135_alter_encounter_header_image_alter_event_cover_image_and_more",
        )
    ]

    operations = [
        migrations.RunPython(purge_blank_field_values, migrations.RunPython.noop)
    ]
