import ast
import json

from django.db import migrations, models


def convert_string_values_to_json(apps, schema_editor):
    """Parse stringified lists into actual lists for JSONField storage."""
    SessionFieldValue = apps.get_model("db_main", "SessionFieldValue")
    HostPersonalData = apps.get_model("db_main", "HostPersonalData")

    for model in [SessionFieldValue, HostPersonalData]:
        for obj in model.objects.all():
            val = obj.value
            if isinstance(val, str) and val.startswith("["):
                try:
                    parsed = json.loads(val)
                    obj.value = parsed
                    obj.save(update_fields=["value"])
                    continue
                except json.JSONDecodeError, ValueError:
                    pass
                try:
                    parsed = ast.literal_eval(val)
                    if isinstance(parsed, list):
                        obj.value = parsed
                        obj.save(update_fields=["value"])
                except ValueError, SyntaxError:
                    pass


class Migration(migrations.Migration):

    dependencies = [
        ("db_main", "0051_personaldatafield_help_text_sessionfield_help_text")
    ]

    operations = [
        migrations.AlterField(
            model_name="personaldatafield",
            name="field_type",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("select", "Select"),
                    ("checkbox", "Checkbox"),
                ],
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="sessionfield",
            name="field_type",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("select", "Select"),
                    ("checkbox", "Checkbox"),
                ],
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="hostpersonaldata",
            name="value",
            field=models.JSONField(default=""),
        ),
        migrations.AlterField(
            model_name="sessionfieldvalue",
            name="value",
            field=models.JSONField(default=""),
        ),
        migrations.RunPython(convert_string_values_to_json, migrations.RunPython.noop),
    ]
