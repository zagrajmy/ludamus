import pytest
from django.urls import reverse

from ludamus.pacts.user import AgeBand
from tests.integration.conftest import SphereFactory


def _open(response) -> bool:
    return bool(response.context["PARLEY_OPEN"])


@pytest.mark.usefixtures("parley_settings")
def test_the_chat_opens_on_any_sphere_for_someone_with_a_room_elsewhere(
    authenticated_client, active_user, sphere
):
    sphere.parley_enabled = False
    sphere.save()
    SphereFactory().managers.add(active_user)

    response = authenticated_client.get(reverse("web:index"))

    assert _open(response) is True


@pytest.mark.usefixtures("parley_settings")
def test_the_chat_stays_shut_to_someone_with_nowhere_to_chat(authenticated_client):
    response = authenticated_client.get(reverse("web:index"))

    assert _open(response) is False


@pytest.mark.usefixtures("parley_settings")
def test_the_chat_opens_to_anyone_direct_messages_are_open_to(
    authenticated_client, active_user
):
    active_user.age_band = AgeBand.SIXTEEN_PLUS
    active_user.save()

    response = authenticated_client.get(reverse("web:index"))

    assert _open(response) is True


def test_the_chat_stays_shut_where_no_worker_is_configured(
    authenticated_client, active_user, sphere
):
    sphere.managers.add(active_user)

    response = authenticated_client.get(reverse("web:index"))

    assert _open(response) is False


@pytest.mark.usefixtures("parley_settings")
def test_the_chat_stays_shut_to_someone_signed_out(client):
    response = client.get(reverse("web:index"))

    assert _open(response) is False
