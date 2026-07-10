from django.db import migrations


def backfill_event(apps, schema_editor):
    Session = apps.get_model("db_main", "Session")
    # Scheduled proposals reach their event through the agenda chain; everything
    # else through its category. coalesce: category first, agenda chain second.
    for session in Session.objects.filter(event__isnull=True).select_related(
        "category", "agenda_item__space__area__venue"
    ):
        category_event_id = session.category.event_id if session.category_id else None
        agenda_event_id = (
            session.agenda_item.space.area.venue.event_id
            if hasattr(session, "agenda_item")
            else None
        )
        if (
            category_event_id is not None
            and agenda_event_id is not None
            and category_event_id != agenda_event_id
        ):
            msg = (
                f"Session {session.pk}: category event {category_event_id} != "
                f"agenda event {agenda_event_id}"
            )
            raise ValueError(msg)
        event_id = category_event_id or agenda_event_id
        if event_id is None:
            continue
        session.event_id = event_id
        session.save(update_fields=["event"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0095_session_event")]

    operations = [migrations.RunPython(backfill_event, migrations.RunPython.noop)]
