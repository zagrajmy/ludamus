from django.db import migrations


def populate_facilitators(apps, schema_editor):
    Session = apps.get_model("db_main", "Session")
    for session in Session.objects.filter(proposed_by__isnull=False).select_related(
        "proposed_by"
    ):
        session.facilitators.add(session.proposed_by)


class Migration(migrations.Migration):

    dependencies = [("db_main", "0066_track_session_tracks_and_more")]

    operations = [
        migrations.RunPython(populate_facilitators, migrations.RunPython.noop)
    ]
