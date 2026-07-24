import re

from django.core.files.uploadedfile import SimpleUploadedFile

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
