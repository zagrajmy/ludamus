import re

from django.core.files.uploadedfile import SimpleUploadedFile

from ludamus.links.db.django.repositories.storage import save_replacing_files
from ludamus.pacts.images import ORIGINAL_FILENAME_MAX_LENGTH
from tests.integration.conftest import PNG_BYTES


class TestUniqueUploadTo:
    def test_same_filename_uploaded_twice_gets_distinct_names(self, agenda_item):
        session = agenda_item.session
        stored = r"sessions/[0-9a-f]{32}\.png"

        names = []
        for _ in range(2):
            session.cover_image = SimpleUploadedFile(
                "image.PNG", PNG_BYTES, content_type="image/png"
            )
            session.save()
            names.append(session.cover_image.name)

        assert names[0] != names[1]
        assert all(re.fullmatch(stored, name) for name in names)

    def test_unlisted_suffix_is_dropped(self, agenda_item):
        session = agenda_item.session

        session.cover_image = SimpleUploadedFile(
            "image.html", PNG_BYTES, content_type="image/png"
        )
        session.save()

        assert re.fullmatch(r"sessions/[0-9a-f]{32}", session.cover_image.name)


class TestOriginalFilename:
    def test_stores_original_basename_beside_the_file(self, agenda_item):
        session = agenda_item.session
        save_replacing_files(
            session,
            {
                "cover_image": SimpleUploadedFile(
                    r"..\My Cool Cover.PNG", PNG_BYTES, content_type="image/png"
                )
            },
        )
        session.refresh_from_db()

        assert session.cover_image_original_name == "My Cool Cover.PNG"
        assert re.fullmatch(r"sessions/[0-9a-f]{32}\.png", session.cover_image.name)

    def test_clears_original_name_with_the_file(self, agenda_item):
        session = agenda_item.session
        save_replacing_files(
            session,
            {
                "cover_image": SimpleUploadedFile(
                    "poster.png", PNG_BYTES, content_type="image/png"
                )
            },
        )
        save_replacing_files(session, {"cover_image": ""})
        session.refresh_from_db()

        assert not session.cover_image
        assert not session.cover_image_original_name

    def test_caps_original_name_at_contract_length(self, agenda_item):
        session = agenda_item.session
        too_long = "a" * (ORIGINAL_FILENAME_MAX_LENGTH + 10) + ".png"
        save_replacing_files(
            session,
            {
                "cover_image": SimpleUploadedFile(
                    too_long, PNG_BYTES, content_type="image/png"
                )
            },
        )
        session.refresh_from_db()

        assert len(session.cover_image_original_name) == ORIGINAL_FILENAME_MAX_LENGTH
