from django.db import migrations, models


def _public_field_ids(apps, event_id: int) -> set[int]:
    session_field = apps.get_model("db_main", "SessionField")
    return set(
        session_field.objects.filter(event_id=event_id, is_public=True).values_list(
            "pk", flat=True
        )
    )


def hide_undisplayed_fields(apps, _schema_editor) -> None:
    # An event that picked none never chose to hide its fields; it now shows them all.
    event_settings = apps.get_model("db_main", "EventSettings")
    for settings in event_settings.objects.prefetch_related("displayed_session_fields"):
        if displayed := {field.pk for field in settings.displayed_session_fields.all()}:
            settings.hidden_session_fields.set(
                _public_field_ids(apps, settings.event_id) - displayed
            )


def display_unhidden_fields(apps, _schema_editor) -> None:
    event_settings = apps.get_model("db_main", "EventSettings")
    for settings in event_settings.objects.prefetch_related("hidden_session_fields"):
        hidden = {field.pk for field in settings.hidden_session_fields.all()}
        settings.displayed_session_fields.set(
            _public_field_ids(apps, settings.event_id) - hidden
        )


class Migration(migrations.Migration):
    dependencies = [("db_main", "0166_sphere_visibility")]

    operations = [
        migrations.AddField(
            model_name="eventsettings",
            name="hidden_session_fields",
            field=models.ManyToManyField(
                blank=True, related_name="+", to="db_main.sessionfield"
            ),
        ),
        migrations.RunPython(hide_undisplayed_fields, display_unhidden_fields),
        migrations.RemoveField(
            model_name="eventsettings", name="displayed_session_fields"
        ),
    ]
