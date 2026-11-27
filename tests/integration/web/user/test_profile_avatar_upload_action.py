from http import HTTPStatus

from django.contrib.messages import constants
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.links.db.django.models import User
from ludamus.pacts.user import UserDTO, gravatar_url
from tests.integration.conftest import PNG_BYTES
from tests.integration.utils import FormErrorsMatcher, assert_response

URL = reverse("web:crowd:profile-avatar-upload")
PAGE_URL = reverse("web:crowd:profile-avatar")


def _photo(name="me.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


class TestProfileAvatarUploadActionView:
    def test_post_stores_the_photo(self, authenticated_client, active_user):
        response = authenticated_client.post(URL, {"uploaded_avatar": _photo()})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Photo saved."),),
            url=PAGE_URL,
        )
        user = User.objects.get(pk=active_user.pk)
        assert (bool(user.uploaded_avatar), user.uploaded_avatar_original_name) == (
            True,
            "me.png",
        )

    def test_post_clear_removes_the_photo_and_its_file(
        self, authenticated_client, active_user, django_capture_on_commit_callbacks
    ):
        active_user.uploaded_avatar = _photo()
        active_user.save()
        storage, name = (
            active_user.uploaded_avatar.storage,
            active_user.uploaded_avatar.name,
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(URL, {"uploaded_avatar-clear": "on"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Photo removed."),),
            url=PAGE_URL,
        )
        user = User.objects.get(pk=active_user.pk)
        assert (user.uploaded_avatar.name, user.uploaded_avatar_original_name) == (
            "",
            "",
        )
        assert not storage.exists(name)

    def test_post_without_a_file_changes_nothing(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.post(URL, {})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.INFO, "Choose a photo to upload first."),),
            url=PAGE_URL,
        )
        assert not User.objects.get(pk=active_user.pk).uploaded_avatar

    def test_post_refuses_a_file_that_is_not_an_image(
        self, authenticated_client, active_user
    ):
        fake = SimpleUploadedFile("me.png", b"not a png", content_type="image/png")

        response = authenticated_client.post(URL, {"uploaded_avatar": fake})

        assert_response(
            response,
            HTTPStatus.OK,
            messages=((constants.WARNING, "Please correct the errors below."),),
            context_data={
                "user": UserDTO.model_validate(active_user),
                "gravatar_url": gravatar_url(active_user.email),
                "has_auth0_avatar": False,
                "upload_form": FormErrorsMatcher(
                    uploaded_avatar=[
                        (
                            "Upload a valid image. The file you uploaded was "
                            "either not an image or a corrupted image."
                        )
                    ]
                ),
                "profile_active_tab": "avatar",
            },
            template_name="user/user/avatar.html",
        )
        assert not User.objects.get(pk=active_user.pk).uploaded_avatar

    def test_unauthenticated_post_redirects_to_login(self, client, active_user):
        response = client.post(URL, {"uploaded_avatar": _photo()})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )
        assert not User.objects.get(pk=active_user.pk).uploaded_avatar
