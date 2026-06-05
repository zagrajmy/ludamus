from django.core.files.uploadedfile import SimpleUploadedFile

from ludamus.links.db.django.repositories import SessionRepository, delete_stored_file

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01"
    b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_delete_stored_file_noop_without_storage():
    delete_stored_file(object(), "orphan/path.png")


class TestSessionRepositoryCoverUpdate:
    def test_replacing_cover_deletes_previous_file(self, agenda_item):
        session = agenda_item.session
        session.cover_image = SimpleUploadedFile(
            "old.png", PNG_BYTES, content_type="image/png"
        )
        session.save()
        storage = session.cover_image.storage
        old_name = session.cover_image.name
        new_image = SimpleUploadedFile("new.png", PNG_BYTES, content_type="image/png")

        SessionRepository.update(session.pk, {"cover_image": new_image})

        session.refresh_from_db()
        assert session.cover_image.name != old_name
        assert not storage.exists(old_name)
