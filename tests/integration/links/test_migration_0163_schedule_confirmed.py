from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ludamus.links.db.django.models import AgendaItem
from tests.integration.conftest import AgendaItemFactory, SessionFactory

backfill_schedule_confirmed = import_module(
    "ludamus.links.db.django.migrations.0163_session_schedule_confirmed"
).backfill_schedule_confirmed


@pytest.fixture(name="apps_at_0163")
def apps_at_0163_fixture():
    # The backfill runs right after the AddField in the same migration.
    return (
        MigrationLoader(connection)
        .project_state(("db_main", "0163_session_schedule_confirmed"))
        .apps
    )


@pytest.mark.django_db
class TestBackfillScheduleConfirmed:
    def test_copies_the_flag_from_the_agenda_item(self, apps_at_0163):
        confirmed = AgendaItemFactory()
        AgendaItem.objects.filter(pk=confirmed.pk).update(session_confirmed=True)
        unconfirmed = AgendaItemFactory()
        unplaced = SessionFactory()

        backfill_schedule_confirmed(apps_at_0163, None)

        confirmed.session.refresh_from_db()
        unconfirmed.session.refresh_from_db()
        unplaced.refresh_from_db()
        assert confirmed.session.schedule_confirmed is True
        assert unconfirmed.session.schedule_confirmed is False
        assert unplaced.schedule_confirmed is False
