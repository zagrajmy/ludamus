from django.db import migrations, models


def copy_name_to_question(apps, _schema_editor):
    PersonalDataField = apps.get_model("db_main", "PersonalDataField")
    PersonalDataField.objects.update(question=models.F("name"))

    SessionField = apps.get_model("db_main", "SessionField")
    SessionField.objects.update(question=models.F("name"))


class Migration(migrations.Migration):

    dependencies = [
        ("db_main", "0053_rename_presenter_name_session_display_name_and_more")
    ]

    operations = [
        migrations.AddField(
            model_name="personaldatafield",
            name="question",
            field=models.CharField(default="", max_length=500),
        ),
        migrations.AddField(
            model_name="sessionfield",
            name="question",
            field=models.CharField(default="", max_length=500),
        ),
        migrations.RunPython(copy_name_to_question, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="personaldatafield",
            name="question",
            field=models.CharField(max_length=500),
        ),
        migrations.AlterField(
            model_name="sessionfield",
            name="question",
            field=models.CharField(max_length=500),
        ),
    ]
