import base64
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from ludamus.links.db.django.previews import (
    PREVIEW_MAX_LENGTH,
    PREVIEW_WIDTH,
    image_preview,
)
from ludamus.links.db.django.repositories import EventRepository
from tests.integration.conftest import PNG_BYTES


def _decode(uri: str) -> bytes:
    return base64.b64decode(uri.removeprefix("data:image/webp;base64,"))


def _upload(name: str = "cover.png", *, size: tuple[int, int] = (640, 360)):
    image = Image.new("RGB", size)
    for x in range(size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class TestImagePreview:
    def test_encodes_a_webp_data_uri(self):
        assert image_preview(_upload()).startswith("data:image/webp;base64,")

    def test_fits_under_the_inline_cap(self):
        assert len(image_preview(_upload())) <= PREVIEW_MAX_LENGTH

    def test_keeps_the_source_aspect_ratio(self):
        uri = image_preview(_upload(size=(640, 160)))
        preview = Image.open(BytesIO(_decode(uri)))
        assert preview.size == (PREVIEW_WIDTH, 5)

    def test_rewinds_the_file_for_storage(self):
        upload = _upload()
        image_preview(upload)
        assert upload.tell() == 0

    def test_unreadable_file_yields_no_preview(self):
        upload = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        assert not image_preview(upload)


@pytest.mark.django_db
class TestEventCoverPreview:
    def test_uploading_a_cover_derives_its_preview(self, event):
        EventRepository.update(event.pk, {"cover_image": _upload()})

        event.refresh_from_db()
        assert event.cover_image_preview.startswith("data:image/webp;base64,")

    def test_clearing_the_cover_clears_the_preview(self, event):
        EventRepository.update(event.pk, {"cover_image": _upload()})

        EventRepository.update(event.pk, {"cover_image": ""})

        event.refresh_from_db()
        assert not event.cover_image_preview

    def test_a_written_cover_still_reaches_storage_whole(self, event):
        EventRepository.update(
            event.pk, {"cover_image": SimpleUploadedFile("c.png", PNG_BYTES)}
        )

        event.refresh_from_db()
        assert event.cover_image.read() == PNG_BYTES
