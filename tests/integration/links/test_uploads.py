import re

from django.core.files.uploadedfile import SimpleUploadedFile

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
