from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from unittest.mock import ANY

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.adapters.db.django.models import Encounter
from tests.integration.utils import assert_response


class TestEncounterCreatePageView:
    URL = reverse("web:notice-board:create")

    def test_login_required(self, client):
        response = client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.FOUND,
            url="/crowd/login-required/?next=/encounters/create/",
        )

    def test_ok_get(self, authenticated_client):
        response = authenticated_client.get(self.URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )

    def test_ok_post(self, authenticated_client, sphere):
        start = datetime.now(UTC) + timedelta(days=7)
        data = {
            "title": "Board Game Night",
            "description": "Let's play some games!",
            "game": "Catan",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "place": "My house",
            "max_participants": 4,
        }

        response = authenticated_client.post(self.URL, data)

        encounter = Encounter.objects.get(title="Board Game Night")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert encounter.game == "Catan"
        assert encounter.max_participants == data["max_participants"]
        assert encounter.share_code
        assert encounter.sphere == sphere

    def test_ok_post_with_blank_max_participants(self, authenticated_client, sphere):
        start = datetime.now(UTC) + timedelta(days=7)
        data = {
            "title": "Unlimited Board Game Night",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "max_participants": "",
        }

        response = authenticated_client.post(self.URL, data)

        encounter = Encounter.objects.get(title="Unlimited Board Game Night")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert encounter.max_participants == 0
        assert encounter.sphere == sphere

    def test_ok_post_with_header_image(self, authenticated_client, sphere):
        start = datetime.now(UTC) + timedelta(days=7)
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
            b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        image = SimpleUploadedFile("header.png", png_bytes, content_type="image/png")
        data = {
            "title": "Image Night",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "max_participants": 4,
            "header_image": image,
        }

        response = authenticated_client.post(self.URL, data)

        encounter = Encounter.objects.get(title="Image Night")
        assert_response(
            response,
            HTTPStatus.FOUND,
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        assert encounter.header_image
        assert encounter.sphere == sphere

    def test_rejects_unsupported_header_image_format(self, authenticated_client):
        start = datetime.now(UTC) + timedelta(days=7)
        gif_bytes = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
            b"\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        image = SimpleUploadedFile("header.gif", gif_bytes, content_type="image/gif")
        data = {
            "title": "Wrong Format Night",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "max_participants": 4,
            "header_image": image,
        }

        response = authenticated_client.post(self.URL, data)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert response.context["form"].errors["header_image"] == [
            "Unsupported image format. Use JPG, PNG, WebP, or AVIF."
        ]
        assert not Encounter.objects.filter(title="Wrong Format Night").exists()

    def test_image_too_large(self, authenticated_client):
        start = datetime.now(UTC) + timedelta(days=7)
        gif_header = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
            b"\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        oversized = gif_header + b"\x00" * (2 * 1024 * 1024 + 1)
        image = SimpleUploadedFile("big.gif", oversized, content_type="image/gif")
        data = {
            "title": "Too Large Image",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "max_participants": 4,
            "header_image": image,
        }

        response = authenticated_client.post(self.URL, data)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert "header_image" in response.context["form"].errors

    def test_end_time_before_start_time(self, authenticated_client):
        start = datetime.now(UTC) + timedelta(days=7)
        data = {
            "title": "Bad Times",
            "start_time": start.strftime("%Y-%m-%dT%H:%M"),
            "end_time": (start - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "max_participants": 4,
        }

        response = authenticated_client.post(self.URL, data)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert "end_time" in response.context["form"].errors

    def test_invalid_form(self, authenticated_client):
        response = authenticated_client.post(self.URL, {})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={"form": ANY},
            template_name="notice_board/create.html",
        )
        assert response.context["form"].errors
