from datetime import UTC, datetime
from http import HTTPStatus
from unittest.mock import ANY

from django.urls import reverse
from freezegun import freeze_time

from ludamus.adapters.web.django.design_fixtures import (
    mock_event_info,
    mock_session_data,
    mock_session_data_ended,
    mock_user,
)
from tests.integration.utils import assert_response

FROZEN_TIME = "2026-01-15 12:00:00"
FROZEN_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


class TestDesignPageView:
    URL = reverse("web:design")

    @freeze_time(FROZEN_TIME)
    def test_ok(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "view": ANY,
                "design_event": mock_event_info(),
                "design_session_data": mock_session_data(),
                "design_session_data_ended": mock_session_data_ended(),
                "design_user": mock_user(),
                "design_form": ANY,
                "design_radio_options": [
                    ("a", "Radio A", True, "design-radio-a"),
                    ("b", "Radio B", False, "design-radio-b"),
                ],
            },
            template_name=["design.html"],
            contains=["py-1.5", "py-2", "py-3", "text-xs", "text-sm", "text-base"],
            cache_control={"public", "max-age=300"},
        )
