from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ludamus.links.db.django.models import AgendaItem, Session
from tests.integration.conftest import AgendaItemFactory, SessionFactory

backfill_schedule_confirmed = import_module(
    "ludamus.links.db.django.migrations.0206_backfill_schedule_confirmed"
).backfill_schedule_confirmed


@pytest.fixture(name="apps_at_0206")
def apps_at_0206_fixture():
    return (
        MigrationLoader(connection)
        .project_state(("db_main", "0206_backfill_schedule_confirmed"))
        .apps
    )


@pytest.mark.django_db
class TestBackfillScheduleConfirmed:
    def test_copies_confirmations_the_session_column_missed(self, apps_at_0206):
        missed = AgendaItemFactory()
        AgendaItem.objects.filter(pk=missed.pk).update(session_confirmed=True)
        in_step = AgendaItemFactory(session_confirmed=True)
        unconfirmed = AgendaItemFactory()
        unplaced = SessionFactory()

        backfill_schedule_confirmed(apps_at_0206, None)

        for placed in (missed, in_step, unconfirmed):
            placed.session.refresh_from_db()
        unplaced.refresh_from_db()
        assert missed.session.schedule_confirmed is True
        assert in_step.session.schedule_confirmed is True
        assert unconfirmed.session.schedule_confirmed is False
        assert unplaced.schedule_confirmed is False

    def test_copies_a_withdrawn_confirmation(self, apps_at_0206):
        withdrawn = AgendaItemFactory(session_confirmed=False)
        Session.objects.filter(pk=withdrawn.session.pk).update(schedule_confirmed=True)
        unplaced = SessionFactory(schedule_confirmed=True)

        backfill_schedule_confirmed(apps_at_0206, None)

        withdrawn.session.refresh_from_db()
        unplaced.refresh_from_db()
        assert withdrawn.session.schedule_confirmed is False
        assert unplaced.schedule_confirmed is False

    def test_reaches_a_soft_deleted_session(self, apps_at_0206):
        deleted = AgendaItemFactory()
        AgendaItem.objects.filter(pk=deleted.pk).update(session_confirmed=True)
        deleted.session.soft_delete()

        backfill_schedule_confirmed(apps_at_0206, None)

        deleted.session.refresh_from_db()
        assert deleted.session.schedule_confirmed is True
