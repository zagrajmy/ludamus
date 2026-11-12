from datetime import UTC, datetime
from importlib import import_module

from django.apps import apps

from ludamus.links.db.django.models import ParleyReport
from tests.integration.conftest import UserFactory

migration = import_module("ludamus.links.db.django.migrations.0193_moderation_notices")


def _report(sphere, *, message_id, resolved_at):
    return ParleyReport.objects.create(
        sphere=sphere,
        reporter=UserFactory(),
        room_id=f"sphere:{sphere.pk}",
        message_id=message_id,
        resolved_at=resolved_at,
    )


def test_reports_resolved_before_decisions_close_and_open_ones_stay_open(sphere):
    resolved = _report(
        sphere, message_id=1, resolved_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    waiting = _report(sphere, message_id=2, resolved_at=None)

    migration.close_resolved_chat_reports(apps, None)

    resolved.refresh_from_db()
    waiting.refresh_from_db()
    assert (resolved.status, resolved.decision, resolved.decision_text) == (
        "rejected",
        "no_action",
        migration.PREDATES_DECISIONS,
    )
    assert (waiting.status, waiting.decision, waiting.decision_text) == ("open", "", "")
