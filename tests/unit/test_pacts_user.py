from ludamus.pacts.user import AvatarSource, display_avatar_url


def _gravatar(email: str) -> str:
    return f"https://gravatar/{email}"


class TestDisplayAvatarUrl:
    def test_a_stored_photo_does_not_override_the_gravatar_choice(self):
        url = display_avatar_url(
            email="me@example.com",
            avatar_url="https://provider/pic",
            uploaded_avatar_url="/media/users/me.png",
            avatar_source=AvatarSource.GRAVATAR,
            gravatar=_gravatar,
        )

        assert url == "https://gravatar/me@example.com"

    def test_the_photo_choice_shows_the_photo(self):
        url = display_avatar_url(
            email="me@example.com",
            avatar_url="https://provider/pic",
            uploaded_avatar_url="/media/users/me.png",
            avatar_source=AvatarSource.UPLOADED,
            gravatar=_gravatar,
        )

        assert url == "/media/users/me.png"

    def test_the_photo_choice_without_a_photo_falls_back_to_the_provider(self):
        url = display_avatar_url(
            email="me@example.com",
            avatar_url="https://provider/pic",
            uploaded_avatar_url="",
            avatar_source=AvatarSource.UPLOADED,
            gravatar=_gravatar,
        )

        assert url == "https://provider/pic"

    def test_no_provider_picture_falls_back_to_gravatar(self):
        url = display_avatar_url(
            email="me@example.com",
            avatar_url="",
            uploaded_avatar_url="",
            avatar_source=AvatarSource.PROVIDER,
            gravatar=_gravatar,
        )

        assert url == "https://gravatar/me@example.com"
