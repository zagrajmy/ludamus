from django.db import migrations


def backfill_event(apps, schema_editor):
    Session = apps.get_model("db_main", "Session")
    # Scheduled proposals reach their event through the agenda chain; everything
    # else through its category. coalesce: category first, agenda chain second.
    for session in Session.objects.filter(event__isnull=True).select_related(
        "category", "agenda_item__space__area__venue"
    ):
        if session.category_id:
            session.event_id = session.category.event_id
        elif hasattr(session, "agenda_item"):
            session.event_id = session.agenda_item.space.area.venue.event_id
        else:
            continue
        session.save(update_fields=["event"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0095_session_event")]

    operations = [migrations.RunPython(backfill_event, migrations.RunPython.noop)]
