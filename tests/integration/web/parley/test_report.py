from http import HTTPStatus

from django.urls import reverse

from ludamus.links.db.django.models import ParleyReport
from tests.integration.conftest import SphereFactory
from tests.integration.utils import assert_response

MESSAGE_ID = 42


def test_report_is_scoped_to_an_accessible_room(
    authenticated_client, active_user, sphere
):
    sphere.parley_enabled = True
    sphere.save()

    response = authenticated_client.post(
        reverse("parley_report"),
        data={
            "message_id": MESSAGE_ID,
            "reason": "Spam",
            "room_id": f"sphere:{sphere.pk}",
        },
    )

    assert_response(response, HTTPStatus.CREATED)
    report = ParleyReport.objects.get()
    assert report.sphere == sphere
    assert report.reporter == active_user
    assert report.room_id == f"sphere:{sphere.pk}"
    assert report.message_id == MESSAGE_ID
    assert report.reason == "Spam"


def test_report_rejects_a_foreign_room_without_side_effects(
    authenticated_client, sphere
):
    sphere.parley_enabled = True
    sphere.save()
    foreign = SphereFactory(parley_enabled=True)

    response = authenticated_client.post(
        reverse("parley_report"),
        data={"message_id": MESSAGE_ID, "room_id": f"sphere:{foreign.pk}"},
    )

    assert_response(response, HTTPStatus.UNPROCESSABLE_CONTENT)
    assert not ParleyReport.objects.exists()
