from django.db import migrations

from ludamus.pacts.durations import normalize_duration


def normalize_stored_durations(apps, schema_editor):
    del schema_editor
    # Durations reached storage as whatever their author typed ("P4H",
    # "50min", "110m"). Rewrite them in the one format readers understand;
    # anything unreadable becomes unset rather than shown raw.
    session_model = apps.get_model("db_main", "Session")
    # Soft-deleted rows included: restoring a session must not bring an
    # unreadable duration back with it.
    for session in session_model.objects.exclude(duration="").iterator():
        if (normalized := normalize_duration(session.duration)) != session.duration:
            session.duration = normalized
            session.save(update_fields=["duration"])

    category_model = apps.get_model("db_main", "ProposalCategory")
    for category in category_model.objects.iterator():
        normalized_durations = [
            normalized
            for duration in category.durations or []
            if (normalized := normalize_duration(duration))
        ]
        if normalized_durations != category.durations:
            category.durations = normalized_durations
            category.save(update_fields=["durations"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0141_eventpanelsettings_proposal_columns")]

    operations = [
        migrations.RunPython(normalize_stored_durations, migrations.RunPython.noop)
    ]
