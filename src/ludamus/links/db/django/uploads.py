from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from django.utils.text import get_valid_filename

from ludamus.pacts.images import UPLOAD_SUFFIXES

if TYPE_CHECKING:
    from django.db import models

_MAX_ORIGINAL_STEM = 80


def unique_upload_to(instance: models.Model, filename: str) -> str:
    # User-supplied filenames collide (every phone ships an "image.png"), and on
    # GCS a collision overwrites the earlier file instead of getting a suffix, so
    # the uuid directory carries uniqueness. The original basename is the last
    # path segment so the dropzone can show a name humans recognize. The folder
    # follows the model name, which means renaming a model redirects new uploads
    # and strands the old folder.
    # The suffix decides the served content type and is the one part of an upload
    # the form validators don't check (they trust the format Pillow detects, not
    # the name), so anything off the allowlist is dropped rather than letting an
    # image be served as .html.
    model_name = type(instance).__name__.lower()
    original = Path(filename.replace("\\", "/")).name
    if (suffix := Path(original).suffix.lower()) not in UPLOAD_SUFFIXES:
        return f"{model_name}s/{uuid4().hex}"
    stem = get_valid_filename(Path(original).stem)[:_MAX_ORIGINAL_STEM] or "file"
    return f"{model_name}s/{uuid4().hex}/{stem}{suffix}"
