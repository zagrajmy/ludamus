from ludamus.pacts.user import display_avatar_url


def _gravatar(email: str) -> str:
    return f"https://gravatar/{email}"


class TestDisplayAvatarUrl:
    def test_uploaded_photo_wins_over_the_gravatar_choice(self):
        url = display_avatar_url(
            email="me@example.com",
            avatar_url="https://provider/pic",
            uploaded_avatar_url="/media/users/me.png",
            use_gravatar=True,
            gravatar=_gravatar,
        )

        assert url == "/media/users/me.png"

    def test_without_a_photo_the_gravatar_choice_still_applies(self):
        url = display_avatar_url(
            email="me@example.com",
            avatar_url="https://provider/pic",
            uploaded_avatar_url="",
            use_gravatar=True,
            gravatar=_gravatar,
        )

        assert url == "https://gravatar/me@example.com"
