from http import HTTPStatus
from unittest.mock import ANY

from django.contrib.messages import constants
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.pacts import EncounterDTO
from tests.integration.conftest import EncounterFactory
from tests.integration.utils import assert_response, assert_response_404

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


class TestEncounterEditPageView:
    def _url(self, pk):
        return reverse("web:notice-board:edit", kwargs={"pk": pk})

    def test_login_required(self, client, encounter):
        response = client.get(self._url(encounter.pk))

        assert_response(
            response,
            HTTPStatus.FOUND,
            url=f"/crowd/login-required/?next=/encounters/{encounter.pk}/edit/",
        )

    def test_ok_get(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)

        response = authenticated_client.get(self._url(encounter.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": ANY,
                "encounter": EncounterDTO.model_validate(encounter),
            },
            template_name="notice_board/edit.html",
        )

    def test_not_creator(self, authenticated_client, encounter):
        response = authenticated_client.get(self._url(encounter.pk))

        assert_response_404(response)

    def test_ok_post(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)

        response = authenticated_client.post(
            self._url(encounter.pk),
            {
                "title": "Updated Title",
                "start_time": "2026-06-01T14:00",
                "max_participants": 5,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Encounter updated."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )

    def test_removes_header_image(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)
        encounter.header_image = SimpleUploadedFile(
            "cover.png", PNG_BYTES, content_type="image/png"
        )
        encounter.save()
        storage = encounter.header_image.storage
        old_name = encounter.header_image.name

        response = authenticated_client.post(
            self._url(encounter.pk),
            {
                "title": encounter.title,
                "start_time": "2026-06-01T14:00",
                "max_participants": 5,
                "header_image-clear": "on",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Encounter updated."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        encounter.refresh_from_db()
        assert not encounter.header_image
        assert not storage.exists(old_name)

    def test_ok_post_with_blank_max_participants(
        self, authenticated_client, user, sphere
    ):
        encounter = EncounterFactory(creator=user, sphere=sphere, max_participants=6)

        response = authenticated_client.post(
            self._url(encounter.pk),
            {
                "title": "Updated Title",
                "start_time": "2026-06-01T14:00",
                "max_participants": "",
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Encounter updated."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )
        encounter.refresh_from_db()
        assert encounter.max_participants == 0

    def test_invalid_form(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)

        response = authenticated_client.post(self._url(encounter.pk), {})

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": ANY,
                "encounter": EncounterDTO.model_validate(encounter),
            },
            template_name="notice_board/edit.html",
        )

    def test_ok_get_without_end_time(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere, end_time=None)

        response = authenticated_client.get(self._url(encounter.pk))

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": ANY,
                "encounter": EncounterDTO.model_validate(encounter),
            },
            template_name="notice_board/edit.html",
        )
        assert not response.context["form"].initial["end_time"]

    def test_ok_post_with_header_image(self, authenticated_client, user, sphere):
        encounter = EncounterFactory(creator=user, sphere=sphere)
        image = SimpleUploadedFile("header.png", PNG_BYTES, content_type="image/png")

        response = authenticated_client.post(
            self._url(encounter.pk),
            {
                "title": "Updated Title",
                "start_time": "2026-06-01T14:00",
                "max_participants": 5,
                "header_image": image,
            },
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Encounter updated."),),
            url=reverse(
                "web:notice-board:encounter-detail",
                kwargs={"share_code": encounter.share_code},
            ),
        )

    def test_rejects_unsupported_header_image_format(
        self, authenticated_client, user, sphere
    ):
        encounter = EncounterFactory(creator=user, sphere=sphere)
        gif_bytes = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
            b"\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        image = SimpleUploadedFile("header.gif", gif_bytes, content_type="image/gif")

        response = authenticated_client.post(
            self._url(encounter.pk),
            {
                "title": "Updated Title",
                "start_time": "2026-06-01T14:00",
                "max_participants": 5,
                "header_image": image,
            },
        )

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "form": ANY,
                "encounter": EncounterDTO.model_validate(encounter),
            },
            template_name="notice_board/edit.html",
        )
        assert response.context["form"].errors["header_image"] == [
            "Unsupported image format. Use JPG, PNG, WebP, or AVIF."
        ]
        encounter.refresh_from_db()
        assert not encounter.header_image

    def test_not_found(self, authenticated_client):
        response = authenticated_client.get(self._url(99999))

        assert_response_404(response)
