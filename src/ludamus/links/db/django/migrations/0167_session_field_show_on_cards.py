from django.db import migrations, models


def hide_unpicked_fields(apps, _schema_editor) -> None:
    # NOTE: an event that picked no fields never chose to hide them; it shows them all.
    event_settings = apps.get_model("db_main", "EventSettings")
    session_field = apps.get_model("db_main", "SessionField")
    for settings in event_settings.objects.prefetch_related("displayed_session_fields"):
        if picked := [field.pk for field in settings.displayed_session_fields.all()]:
            session_field.objects.filter(event_id=settings.event_id).exclude(
                pk__in=picked
            ).update(show_on_cards=False)


def pick_shown_fields(apps, _schema_editor) -> None:
    event_settings = apps.get_model("db_main", "EventSettings")
    session_field = apps.get_model("db_main", "SessionField")
    shown: dict[int, list[int]] = {}
    for event_id, pk in session_field.objects.filter(
        is_public=True, show_on_cards=True
    ).values_list("event_id", "pk"):
        shown.setdefault(event_id, []).append(pk)
    for event_id, field_ids in shown.items():
        settings, _ = event_settings.objects.get_or_create(event_id=event_id)
        settings.displayed_session_fields.set(field_ids)


class Migration(migrations.Migration):
    dependencies = [("db_main", "0166_sphere_visibility")]

    operations = [
        migrations.AddField(
            model_name="sessionfield",
            name="show_on_cards",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(hide_unpicked_fields, pick_shown_fields),
        migrations.DeleteModel(name="EventSettings"),
    ]
