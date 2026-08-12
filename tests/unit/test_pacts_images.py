from ludamus.pacts.images import stored_file_display_name


def test_uses_last_path_segment() -> None:
    assert (
        stored_file_display_name(
            "/media/events/0123456789abcdef0123456789abcdef/poster.png"
        )
        == "poster.png"
    )


def test_decodes_url_escaping() -> None:
    assert stored_file_display_name("/media/events/My%20Cover.png") == "My Cover.png"


def test_hides_hashed_basename() -> None:
    assert not stored_file_display_name(
        "/media/events/0123456789abcdef0123456789abcdef.png"
    )
