from io import StringIO

import pytest
from django.core.management import call_command

from ludamus.links.db.django.models import AgendaItem
from tests.integration.conftest import AgendaItemFactory, SessionFactory

pytestmark = pytest.mark.django_db


def test_copies_confirmations_the_session_column_missed():
    missed = AgendaItemFactory()
    AgendaItem.objects.filter(pk=missed.pk).update(session_confirmed=True)
    in_step = AgendaItemFactory(session_confirmed=True)
    unconfirmed = AgendaItemFactory()
    unplaced = SessionFactory()
    deleted = AgendaItemFactory()
    AgendaItem.objects.filter(pk=deleted.pk).update(session_confirmed=True)
    deleted.session.soft_delete()
    out = StringIO()

    call_command("backfill_schedule_confirmed", stdout=out)

    assert out.getvalue().splitlines() == ["Confirmed the schedule of 2 sessions."]
    for placed in (missed, in_step, unconfirmed, deleted):
        placed.session.refresh_from_db()
    unplaced.refresh_from_db()
    assert missed.session.schedule_confirmed is True
    assert deleted.session.schedule_confirmed is True
    assert in_step.session.schedule_confirmed is True
    assert unconfirmed.session.schedule_confirmed is False
    assert unplaced.schedule_confirmed is False


def test_second_run_changes_nothing():
    missed = AgendaItemFactory()
    AgendaItem.objects.filter(pk=missed.pk).update(session_confirmed=True)
    call_command("backfill_schedule_confirmed", stdout=StringIO())
    out = StringIO()

    call_command("backfill_schedule_confirmed", stdout=out)

    assert out.getvalue().splitlines() == ["Confirmed the schedule of 0 sessions."]
