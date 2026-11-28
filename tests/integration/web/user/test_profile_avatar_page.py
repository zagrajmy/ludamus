from http import HTTPStatus
from unittest.mock import ANY

from django.contrib.messages import constants
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ludamus.links.db.django.models import User
from ludamus.pacts.user import AvatarPageDTO, AvatarSource, UserDTO, gravatar_url
from tests.integration.conftest import PNG_BYTES
from tests.integration.utils import FormErrorsMatcher, assert_response

URL = reverse("web:crowd:profile-avatar")
PROVIDER_PICTURE = "https://example.com/auth0-avatar.png"


def _photo(name="me.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def _page(user, *, available_sources, shown_source):
    return AvatarPageDTO(
        user=UserDTO.model_validate(user),
        gravatar_url=gravatar_url(user.email),
        available_sources=available_sources,
        shown_source=shown_source,
    )


class TestProfileAvatarPageViewGet:
    def test_offers_gravatar_when_there_is_no_other_picture(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "avatar": _page(
                    active_user,
                    available_sources=[AvatarSource.GRAVATAR],
                    shown_source=AvatarSource.GRAVATAR,
                ),
                "form": ANY,
                "profile_active_tab": "avatar",
            },
            template_name="user/user/avatar.html",
        )

    def test_offers_every_source_with_a_picture(
        self, authenticated_client, active_user
    ):
        active_user.avatar_url = PROVIDER_PICTURE
        active_user.uploaded_avatar = _photo()
        active_user.save()

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "avatar": _page(
                    active_user,
                    available_sources=[
                        AvatarSource.UPLOADED,
                        AvatarSource.PROVIDER,
                        AvatarSource.GRAVATAR,
                    ],
                    shown_source=AvatarSource.PROVIDER,
                ),
                "form": ANY,
                "profile_active_tab": "avatar",
            },
            template_name="user/user/avatar.html",
        )

    def test_offers_nothing_without_email_or_pictures(
        self, authenticated_client, active_user
    ):
        active_user.email = ""
        active_user.save()

        response = authenticated_client.get(URL)

        assert_response(
            response,
            HTTPStatus.OK,
            context_data={
                "avatar": _page(
                    active_user,
                    available_sources=[],
                    shown_source=AvatarSource.GRAVATAR,
                ),
                "form": ANY,
                "profile_active_tab": "avatar",
            },
            template_name="user/user/avatar.html",
        )

    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get(URL)

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )


class TestProfileAvatarPageViewPost:
    def test_picks_gravatar(self, authenticated_client, active_user):
        active_user.avatar_url = PROVIDER_PICTURE
        active_user.save()

        response = authenticated_client.post(URL, {"avatar_source": "gravatar"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Avatar updated."),),
            url=URL,
        )
        user = User.objects.get(pk=active_user.pk)
        assert user.avatar_source == AvatarSource.GRAVATAR

    def test_refuses_a_source_without_a_picture(
        self, authenticated_client, active_user
    ):
        response = authenticated_client.post(URL, {"avatar_source": "provider"})

        assert_response(
            response,
            HTTPStatus.OK,
            messages=((constants.WARNING, "Please correct the errors below."),),
            context_data={
                "avatar": _page(
                    active_user,
                    available_sources=[AvatarSource.GRAVATAR],
                    shown_source=AvatarSource.GRAVATAR,
                ),
                "form": FormErrorsMatcher(
                    avatar_source=[
                        (
                            "Select a valid choice. provider is not one of the "
                            "available choices."
                        )
                    ]
                ),
                "profile_active_tab": "avatar",
            },
            template_name="user/user/avatar.html",
        )
        user = User.objects.get(pk=active_user.pk)
        assert user.avatar_source == AvatarSource.PROVIDER

    def test_an_upload_stores_the_photo_and_makes_it_the_avatar(
        self, authenticated_client, active_user
    ):
        active_user.avatar_source = AvatarSource.GRAVATAR
        active_user.save()

        response = authenticated_client.post(
            URL, {"avatar_source": "gravatar", "uploaded_avatar": _photo()}
        )

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Photo saved."),),
            url=URL,
        )
        user = User.objects.get(pk=active_user.pk)
        assert (
            user.avatar_source,
            bool(user.uploaded_avatar),
            user.uploaded_avatar_original_name,
        ) == (AvatarSource.UPLOADED, True, "me.png")

    def test_remove_deletes_the_photo_and_its_file(
        self, authenticated_client, active_user, django_capture_on_commit_callbacks
    ):
        active_user.uploaded_avatar = _photo()
        active_user.avatar_source = AvatarSource.UPLOADED
        active_user.save()
        stored = active_user.uploaded_avatar
        storage, name = stored.storage, stored.name

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post(URL, {"uploaded_avatar-clear": "on"})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.SUCCESS, "Photo removed."),),
            url=URL,
        )
        user = User.objects.get(pk=active_user.pk)
        assert (user.uploaded_avatar.name, user.uploaded_avatar_original_name) == (
            "",
            "",
        )
        assert not storage.exists(name)

    def test_an_empty_post_changes_nothing(self, authenticated_client, active_user):
        response = authenticated_client.post(URL, {})

        assert_response(
            response,
            HTTPStatus.FOUND,
            messages=((constants.INFO, "Pick an avatar or upload a photo."),),
            url=URL,
        )
        user = User.objects.get(pk=active_user.pk)
        assert (user.avatar_source, bool(user.uploaded_avatar)) == (
            AvatarSource.PROVIDER,
            False,
        )

    def test_refuses_a_file_that_is_not_an_image(
        self, authenticated_client, active_user
    ):
        fake = SimpleUploadedFile("me.png", b"not a png", content_type="image/png")

        response = authenticated_client.post(URL, {"uploaded_avatar": fake})

        assert_response(
            response,
            HTTPStatus.OK,
            messages=((constants.WARNING, "Please correct the errors below."),),
            context_data={
                "avatar": _page(
                    active_user,
                    available_sources=[AvatarSource.GRAVATAR],
                    shown_source=AvatarSource.GRAVATAR,
                ),
                "form": FormErrorsMatcher(
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

    def test_unauthenticated_post_changes_nothing(self, client, active_user):
        response = client.post(URL, {"uploaded_avatar": _photo()})

        assert_response(
            response, HTTPStatus.FOUND, url=f"/crowd/login-required/?next={URL}"
        )
        assert not User.objects.get(pk=active_user.pk).uploaded_avatar
