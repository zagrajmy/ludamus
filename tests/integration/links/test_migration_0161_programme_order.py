from importlib import import_module
from types import SimpleNamespace

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from ludamus.links.db.django.models import Space
from tests.integration.conftest import EventFactory

backfill_programme_order = import_module(
    "ludamus.links.db.django.migrations.0161_space_programme_order"
).backfill_programme_order


@pytest.fixture(name="apps_at_0161")
def apps_at_0161_fixture():
    return (
        MigrationLoader(connection)
        .project_state(("db_main", "0161_space_programme_order"))
        .apps
    )


@pytest.mark.django_db
class TestBackfillProgrammeOrder:
    def test_uses_physical_depth_first_order_independently_per_event(
        self, event, sphere, apps_at_0161
    ):
        second_event = EventFactory(sphere=sphere)
        later_root = Space.objects.create(
            event=event, name="Later", slug="later", order=1, programme_order=99
        )
        first_root = Space.objects.create(
            event=event, name="First", slug="first", order=0, programme_order=99
        )
        child_b = Space.objects.create(
            event=event,
            parent=first_root,
            name="B",
            slug="b",
            order=1,
            programme_order=99,
        )
        child_a = Space.objects.create(
            event=event,
            parent=first_root,
            name="A",
            slug="a",
            order=0,
            programme_order=99,
        )
        elsewhere = Space.objects.create(
            event=second_event, name="Elsewhere", slug="elsewhere", programme_order=99
        )

        backfill_programme_order(apps_at_0161, SimpleNamespace(connection=connection))

        assert list(
            Space.objects.filter(event=event)
            .order_by("programme_order")
            .values_list("pk", flat=True)
        ) == [first_root.pk, child_a.pk, child_b.pk, later_root.pk]
        elsewhere.refresh_from_db()
        assert elsewhere.programme_order == 0
