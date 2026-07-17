"""Backfill Session fields from Proposal data (Deploy 2a).

For accepted proposals (session_id IS NOT NULL):
- Copy presenter_id (from host), category_id, needs to the linked Session
- Copy time_slots M2M entries
- Status stays ACCEPTED (already the default)

For pending proposals (session_id IS NULL):
- Create a new Session with status=PENDING
- Set sphere from category.event.sphere
- Set presenter_name from host.name, presenter from host
- Generate slug from title (with uniqueness retry)
- Copy tags + time_slots M2M
- Link Proposal.session_id to the new Session
"""

from django.db import migrations
from django.utils.text import slugify


def _unique_slug(session_model, sphere_id, base_slug):
    slug = base_slug or "session"
    for i in range(100):
        candidate = slug if i == 0 else f"{slug}-{i}"
        if not session_model.objects.filter(
            slug=candidate, sphere_id=sphere_id
        ).exists():
            return candidate
    return f"{slug}-{sphere_id}"


def backfill_sessions(apps, schema_editor):
    Proposal = apps.get_model("db_main", "Proposal")
    Session = apps.get_model("db_main", "Session")

    # --- Accepted proposals: backfill existing Sessions ---
    accepted = Proposal.objects.filter(session__isnull=False).select_related(
        "session", "category", "host"
    )
    for proposal in accepted:
        session = proposal.session
        session.presenter_id = proposal.host_id
        session.category_id = proposal.category_id
        session.needs = proposal.needs or ""
        # status stays ACCEPTED (already the default)
        session.save(update_fields=["presenter_id", "category_id", "needs"])

        # Copy time_slots M2M
        proposal_time_slot_ids = list(proposal.time_slots.values_list("id", flat=True))
        if proposal_time_slot_ids:
            session.time_slots.set(proposal_time_slot_ids)

    # --- Pending proposals: create new Sessions ---
    pending = Proposal.objects.filter(session__isnull=True).select_related(
        "category__event__sphere", "host"
    )
    for proposal in pending:
        sphere = proposal.category.event.sphere
        base_slug = slugify(proposal.title) or "session"

        session = Session.objects.create(
            sphere=sphere,
            presenter_id=proposal.host_id,
            presenter_name=proposal.host.name,
            category_id=proposal.category_id,
            title=proposal.title,
            slug=_unique_slug(Session, sphere.id, base_slug),
            description=proposal.description or "",
            requirements=proposal.requirements or "",
            needs=proposal.needs or "",
            participants_limit=proposal.participants_limit,
            min_age=proposal.min_age,
            status="pending",
        )

        # Copy tags M2M
        tag_ids = list(proposal.tags.values_list("id", flat=True))
        if tag_ids:
            session.tags.set(tag_ids)

        # Copy time_slots M2M
        time_slot_ids = list(proposal.time_slots.values_list("id", flat=True))
        if time_slot_ids:
            session.time_slots.set(time_slot_ids)

        # Link proposal back to the new session
        proposal.session = session
        proposal.save(update_fields=["session_id"])


class Migration(migrations.Migration):

    dependencies = [("db_main", "0042_session_add_pending_status")]

    operations = [migrations.RunPython(backfill_sessions, migrations.RunPython.noop)]
