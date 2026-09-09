from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

import pytest
from django.contrib import messages
from django.urls import reverse

from ludamus.links.db.django.models import Encounter
from tests.integration.conftest import EncounterFactory
from tests.integration.utils import assert_response


def _create_data(**extra):
    start = datetime.now(UTC) + timedelta(days=7)
    return {
        "title": "Open Game Night",
        "start_time": start.strftime("%Y-%m-%dT%H:%M"),
        **extra,
    }


def _assert_redirects_to_detail(response, encounter, **kwargs):
    assert_response(
        response,
        HTTPStatus.FOUND,
        url=reverse(
            "web:notice-board:encounter-detail",
            kwargs={"share_code": encounter.share_code},
        ),
        **kwargs,
    )


@pytest.fixture(name="policy")
def policy_fixture(request, sphere):
    sphere.encounter_public_policy = request.param
    sphere.save()
    return request.param


class TestEncounterPublicFlagOnCreate:
    URL = reverse("web:notice-board:create")

    @pytest.mark.parametrize("policy", ("everyone",), indirect=True)
    def test_form_offers_the_public_toggle_to_allowed_user(
        self, authenticated_client, policy
    ):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert "is_public" in response.context["form"].fields

    @pytest.mark.parametrize("policy", ("disabled",), indirect=True)
    def test_form_hides_the_public_toggle_from_disallowed_user(
        self, authenticated_client, policy
    ):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert "is_public" not in response.context["form"].fields

    @pytest.mark.parametrize("policy", ("everyone",), indirect=True)
    def test_allowed_user_creates_public_encounter(self, authenticated_client, policy):
        response = authenticated_client.post(self.URL, _create_data(is_public="on"))

        encounter = Encounter.objects.get(title="Open Game Night")
        _assert_redirects_to_detail(response, encounter)
        assert encounter.is_public is True

    @pytest.mark.parametrize("policy", ("disabled", "managers"), indirect=True)
    def test_forged_flag_is_ignored_for_disallowed_user(
        self, authenticated_client, policy
    ):
        response = authenticated_client.post(self.URL, _create_data(is_public="on"))

        encounter = Encounter.objects.get(title="Open Game Night")
        _assert_redirects_to_detail(response, encounter)
        assert encounter.is_public is False

    @pytest.mark.parametrize("policy", ("managers",), indirect=True)
    def test_manager_creates_public_encounter(
        self, authenticated_client, active_user, sphere, policy
    ):
        sphere.managers.add(active_user)

        response = authenticated_client.post(self.URL, _create_data(is_public="on"))

        encounter = Encounter.objects.get(title="Open Game Night")
        _assert_redirects_to_detail(response, encounter)
        assert encounter.is_public is True


class TestEncounterPublicFlagOnEdit:
    @pytest.fixture(name="encounter")
    def encounter_fixture(self, sphere, active_user):
        return EncounterFactory(
            sphere=sphere,
            creator=active_user,
            is_public=True,
            start_time=datetime.now(UTC) + timedelta(days=7),
        )

    def _post(self, client, encounter, **extra):
        return client.post(
            reverse("web:notice-board:edit", kwargs={"pk": encounter.pk}),
            _create_data(title=encounter.title, **extra),
        )

    @pytest.mark.parametrize("policy", ("everyone",), indirect=True)
    def test_allowed_user_can_unpublish(self, authenticated_client, encounter, policy):
        response = self._post(authenticated_client, encounter)

        _assert_redirects_to_detail(
            response, encounter, messages=[(messages.SUCCESS, "Encounter updated.")]
        )
        encounter.refresh_from_db()
        assert encounter.is_public is False

    @pytest.mark.parametrize("policy", ("disabled",), indirect=True)
    def test_stored_flag_survives_edit_when_policy_disabled(
        self, authenticated_client, encounter, policy
    ):
        response = self._post(authenticated_client, encounter)

        _assert_redirects_to_detail(
            response, encounter, messages=[(messages.SUCCESS, "Encounter updated.")]
        )
        encounter.refresh_from_db()
        assert encounter.is_public is True
